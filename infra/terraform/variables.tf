variable "project_id" {
  type        = string
  description = "GCP project hosting the Cloud Run services."
  default     = "vf-fraud-detection-phuochoa"
}

variable "region" {
  type        = string
  description = "Region of the Cloud Run services. Must match them, because a serverless NEG is regional."
  default     = "asia-southeast1"
}

variable "backend_service_name" {
  type        = string
  description = "Cloud Run service name for the Flask analysis API."
  default     = "vf-logistics"
}

variable "console_service_name" {
  type        = string
  description = "Cloud Run service name for the Next.js console."
  default     = "vf-console"
}

variable "domain" {
  type        = string
  description = <<-EOT
    Domain for the managed certificate.

    Required, with no default: a Google-managed certificate cannot be issued for
    a *.run.app hostname, so there is no value here that would work without a
    domain you control. Applying with a placeholder produces a certificate stuck
    in PROVISIONING forever, which is a confusing way to discover that.
  EOT
}

# ---------------------------------------------------------------------------
# Pub/Sub
# ---------------------------------------------------------------------------

variable "decisions_topic" {
  type        = string
  description = <<-EOT
    Topic the pipeline publishes each final decision to.

    Must match DECISIONS_TOPIC in the service environment. That variable is
    currently unset on the deployed service, so tools.py falls back to this same
    literal -- changing the default here without also setting DECISIONS_TOPIC
    would leave the code publishing to a topic that no longer exists, and the
    failure is silent because publish_decision_direct swallows it.
  EOT
  default     = "case-decisions"
}

variable "events_topic" {
  type        = string
  description = "Ingress topic for a push subscription to /api/v1/events/shipment."
  default     = "shipment-events"
}

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

variable "rate_limit_requests" {
  type        = number
  description = <<-EOT
    Requests per interval, per IP, before the general ban applies.

    Set well above the application's own 200/min default so the edge catches
    volume the application would not survive, while ordinary dashboard polling
    never reaches it. The application limit stays the tighter of the two for
    normal use; this one is for the case where the application is the thing
    being overwhelmed.
  EOT
  default     = 600
}

variable "rate_limit_interval_sec" {
  type    = number
  default = 60
}

variable "expensive_route_requests" {
  type        = number
  description = <<-EOT
    Per-minute per-IP ceiling on the model-invoking routes.

    Higher than the per-route flask-limiter values on purpose. The application
    limits are the real budget; this is a backstop for the case where instances
    are being replaced fast enough that per-instance counters keep resetting.
  EOT
  default     = 60
}

variable "ban_duration_sec" {
  type        = number
  description = "How long an exceeding IP stays banned. Ten minutes is long enough to make sustained abuse uneconomic and short enough to forgive a misconfigured client."
  default     = 600
}

# ---------------------------------------------------------------------------
# Optional
# ---------------------------------------------------------------------------

variable "enable_adaptive_protection" {
  type        = bool
  description = "Layer 7 DDoS Adaptive Protection. Requires Cloud Armor Enterprise and is billed separately, so it is off by default."
  default     = false
}

variable "blocked_countries" {
  type        = list(string)
  description = "ISO 3166-1 alpha-2 codes to deny. Empty by default -- a trade compliance API has legitimate counterparties nearly everywhere, so this is a decision for whoever knows the customer base."
  default     = []
}
