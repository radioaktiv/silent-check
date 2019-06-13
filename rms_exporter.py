#!/home/christian/radioaktiv/technik/scripts/silent-check/env/bin/python
# {{ ansible_managed }}

import asyncio
import datetime
import logging
import re
import signal

from aiohttp import web
from prometheus_client import Gauge, Info
from prometheus_client import REGISTRY, CONTENT_TYPE_LATEST, generate_latest

logging.basicConfig(format='%(asctime)s : %(levelname)8s : %(name)30s : %(funcName)-20s : %(lineno)4d : %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class Liquidsoap:
    END = 'END\r\n'.encode()

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 loop: asyncio.AbstractEventLoop = None):
        self._reader = reader
        self._writer = writer

        self._reqs = asyncio.Queue()

        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop

    async def send_command(self, command: str) -> str:
        logger.debug('Send command "%s" to liquidsoap' % command)
        if not command.endswith('\n'):
            command += '\n'
        self._writer.write(command.encode())
        await self._writer.drain()

        sep = self.END
        if 'quit' in command or 'exit' in command:
            sep = 'Bye!\r\n'.encode()

        data = await self._reader.readuntil(sep)
        result = data.decode()

        return result[:-len(self.END.decode())]

    async def startup_time(self) -> datetime.datetime:
        pattern = r'(\d+)d (\d{1,2})h (\d{1,2})m (\d{1,2})s'
        res = await self.send_command('uptime')
        now = datetime.datetime.now()
        re_data = re.match(pattern, res)

        try:
            if re_data is not None:
                days, hours, minutes, seconds = re_data.groups()

                uptime = datetime.timedelta(days=int(days),
                                            hours=int(hours),
                                            minutes=int(minutes),
                                            seconds=int(seconds))

                startup_time = now - uptime
                return startup_time
        except Exception as e:
            print(e)

    async def version(self):
        pattern = r'Liquidsoap (?P<version>(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+))'
        res = await self.send_command('version')
        try:
            re_data = re.match(pattern, res)
            return re_data.groupdict()
        except Exception as e:
            print(e)


class Application:
    RMS_SOURCE_SUFFIX = '_rms'

    def __init__(self, liquidsoap: Liquidsoap, bind_addr: str, bind_port: int, metrics_path: str = '/metrics',
                 loop: asyncio.AbstractEventLoop = None):
        self._liquidsoap = liquidsoap
        self._bind_addr = bind_addr
        self._bind_port = bind_port

        self._metrics_path = metrics_path

        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop

        self._sources = []  # type: [str]

        self.rms_gauge = Gauge('liquidsoap_rms', 'The current audio RMS volume of the source.', ['source'])
        self.ls_startup_time = Gauge('liquidsoap_start_time_seconds',
                                     'Start time of the liquidsoap process since unix epoch in seconds.')

        self.ls_version = Info('liquidsoap', 'Liquidsoap version information')

    async def run(self, cleanup_event: asyncio.Event):
        logger.debug('Retrieve and parse sources')
        res = await self._liquidsoap.send_command('help')
        self._sources = [
            line[len('| '):-len(self.RMS_SOURCE_SUFFIX + '.rms')]
            for line in res.splitlines() if '.rms' in line
        ]

        logger.debug('Export startup time of liquidsoap')
        self.ls_startup_time.set(int((await self._liquidsoap.startup_time()).timestamp()))

        logger.debug('Export version information of running liquidsoap instance')
        self.ls_version.info(await self._liquidsoap.version())

        app = web.Application()
        app.router.add_get(self._metrics_path, self.metrics_endpoint)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self._bind_addr, self._bind_port)
        asyncio.create_task(site.start())

        await cleanup_event.wait()

        await self._liquidsoap.send_command('exit')
        await runner.cleanup()

    async def collect_rms_values(self):
        for source in self._sources:
            res = await self._liquidsoap.send_command(source + self.RMS_SOURCE_SUFFIX + '.rms')
            val = float(res)
            self.rms_gauge.labels(source=source).set(val)

    async def metrics_endpoint(self, req):
        await self.collect_rms_values()

        rsp = web.Response(body=generate_latest(REGISTRY))
        # This is set separately because aiohttp complains about `;` in
        # content_type thinking it means there's also a charset.
        # cf. https://github.com/aio-libs/aiohttp/issues/2197
        rsp.content_type = CONTENT_TYPE_LATEST
        return rsp


class AsyncioRunner:
    def __init__(self, loop: asyncio.AbstractEventLoop = None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

        self.cleanup_event = asyncio.Event(loop=self.loop)
        self.cleanup_tasks = []

        self.loop = asyncio.get_event_loop()

    def run_loop(self):
        logger.debug('Install signal handlers on loop')
        for sig_name in ('SIGINT', 'SIGTERM', 'SIGABRT'):
            self.loop.add_signal_handler(getattr(signal, sig_name), self.stop)

        try:
            logger.debug('Start loop forever')
            self.loop.run_forever()
        finally:
            logger.debug('Loop got stopped... running available cleanup tasks')
            if len(self.cleanup_tasks) > 0:
                self.loop.run_until_complete(asyncio.wait(self.cleanup_tasks))
            self.loop.stop()
            self.loop.close()
            logger.warning('End of looping!')

    def stop(self):
        logger.debug('stopping the application, set cleanup event, stop loop')
        self.cleanup_event.set()
        self.loop.stop()

    def start_cleanup_event_task(self, func):
        self.cleanup_tasks.append(self.loop.create_task(func(cleanup_event=self.cleanup_event)))


async def open_liquidsoap_connection(socket_path: str, loop: asyncio.AbstractEventLoop = None):
    logger.debug('Open connection to liquidsoap socket')
    reader, writer = await asyncio.open_unix_connection(socket_path, loop=loop)
    logger.debug('Opened connection to liquidsoap socket')

    return Liquidsoap(reader, writer, loop=loop)


runner = AsyncioRunner()

liquidsoap = runner.loop.run_until_complete(open_liquidsoap_connection('./silent-check.sock', loop=runner.loop))
app = Application(liquidsoap, 'localhost', 8080, loop=runner.loop)

runner.start_cleanup_event_task(app.run)
runner.run_loop()

runner.loop.set_debug(True)
