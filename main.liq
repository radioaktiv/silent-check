settings.prometheus.server.set(true)
settings.prometheus.server.port.set(9033)

settings.log.stdout.set(true)
settings.log.file.set(false)
settings.log.level.set(3)

common_labels = ["station", "variant"]

metric_ready = prometheus.gauge(
  help="Source ready",
  labels=common_labels,
  "radio_source_ready"
)

metric_silence = prometheus.gauge(
  help="Siilence detected on specific source",
  labels=common_labels,
  "radio_audio_silence"
)
metric_rms = prometheus.gauge(
  help="RMS of station / variant",
  labels=common_labels,
  "radio_rms_dezibel"
)

metric_lufs = prometheus.gauge(
  help="LUFS",
  labels=common_labels,
  "radio_lufs"
)
metric_lufs_momentary = prometheus.gauge(
  help="LUFS momentary",
  labels=common_labels,
  "radio_lufs_momentary"
)

def monitor_stream(station, variant, s)
  label_values = [station, variant]
  set_ready = metric_ready(label_values=label_values)
  set_silence = metric_silence(label_values=label_values)
  set_rms = metric_rms(label_values=label_values)
  set_lufs = metric_lufs(label_values=label_values)
  set_lufs_momentary = metric_lufs_momentary(label_values=label_values)

  is_ready = s.is_ready

  s = blank.detect(
    id="blank_" ^ station ^ "_" ^ variant,
    on_noise={set_silence(0.)},
    start_blank=false,
    track_sensitive=false,
    {set_silence(1.)},
    s
  )

  s = mksafe(
    id="mksafe_" ^ station ^ "_" ^ variant,
    s
  )
  s = rms(
    id="rms_" ^ station ^ "_" ^ variant,
    s
  )
  rms = s.rms
  s = lufs(
    id="lufs_" ^ station ^ "_" ^ variant,
    s
  )
  lufs = s.lufs
  lufs_momentary = s.lufs_momentary

  def set_metrics()
    set_ready(if is_ready() then 1. else 0. end)
    set_rms(dB_of_lin(rms()))
    set_lufs(lufs())
    set_lufs_momentary(lufs_momentary())
  end

  output.dummy(
    id="output.dummy_" ^ station ^ "_" ^ variant,
    s
  )

  thread.run(every=1., set_metrics)
end


s = input.http(
  id="in_radioaktiv",
  clock_safe=true,
  new_track_on_metadata=false,
  "https://stream.radioaktiv.org/VeryHiFi"
)

monitor_stream(
  "radioaktiv",
  "VeryHiFi",
  s
)
