{{- define "openzev.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "openzev.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "openzev.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "openzev.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- if .Values.commonLabels }}
{{ toYaml .Values.commonLabels }}
{{- end }}
{{- end -}}

{{- define "openzev.mediaClaimName" -}}
{{- if .Values.media.pvc.existingClaim -}}
{{- .Values.media.pvc.existingClaim -}}
{{- else -}}
{{- printf "%s-media" (include "openzev.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "openzev.imageTag" -}}
{{- if .tag -}}
{{- .tag -}}
{{- else -}}
{{- $appVersion := toString .context.Chart.AppVersion -}}
{{- if hasPrefix "v" $appVersion -}}
{{- $appVersion -}}
{{- else -}}
{{- printf "v%s" $appVersion -}}
{{- end -}}
{{- end -}}
{{- end -}}
