{{/*
Merge one `services[]` entry with `.Values.defaults` (deep merge — service keys win,
nested maps like `thresholds`/`metrics` merge key-by-key rather than replacing wholesale).
Usage: {{- $cfg := include "grafana-monitoring.svcConfig" (dict "svc" $svc "defaults" $.Values.defaults) | fromYaml }}
$cfg then has: name, displayName (defaults to name), namespace, healthCheckPath,
runsTable, metrics.*, maxConcurrency, thresholds.*
*/}}
{{- define "grafana-monitoring.svcConfig" -}}
{{- $merged := merge (deepCopy .svc) .defaults -}}
{{- if not $merged.displayName -}}
{{- $_ := set $merged "displayName" $merged.name -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
Standard folder UID for a service's alert/dashboard folder.
*/}}
{{- define "grafana-monitoring.folderUID" -}}
{{- printf "%s-alerts" . -}}
{{- end -}}
