/**
 * Cloud Armor and the load balancer that hosts it.
 *
 * NOT APPLIED. This directory is committed so the configuration is reviewable
 * and version-controlled, and `terraform validate` runs in CI, but nothing here
 * exists in the project until somebody deliberately runs `terraform apply`.
 *
 * That is a cost decision, not an oversight. A global external Application Load
 * Balancer has a standing charge of roughly USD 18-25 per month before any
 * traffic, plus Cloud Armor policy and request charges. This project runs on a
 * limited Nebius/GCP credit, so the application-layer defences -- the API key,
 * the bounded request size, the per-route rate limits -- were built first
 * because they are free and they close the holes that were actually exploited.
 *
 * What this adds that the application layer cannot:
 *
 *   - Volumetric DDoS absorption. Flask-Limiter refuses a request only after
 *     gunicorn has parsed it and Cloud Run has billed for the instance time.
 *     Cloud Armor refuses at Google's edge.
 *   - A rate limit that is actually global. flask-limiter uses in-process
 *     storage, so its counters are per-instance and reset when an instance is
 *     replaced. Cloud Armor's are neither.
 *   - The OWASP preconfigured rule sets (SQLi, XSS, LFI, RCE, scanner
 *     detection), which nothing in the application attempts.
 *   - Geo and IP policy, which the application has no way to express.
 *
 * Applying this is a two-step change, and the second step is the one that
 * matters: after the load balancer is serving, set the Cloud Run ingress to
 * `internal-and-cloud-load-balancing`, or the *.run.app URL keeps bypassing
 * every rule below. See README for the ordering.
 */

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Cloud Armor security policy
# ---------------------------------------------------------------------------

resource "google_compute_security_policy" "vf_logistics" {
  name        = "vf-logistics-armor"
  description = "Edge policy for the VF Logistics analysis API and console."

  # Adaptive Protection: ML-detected volumetric attacks. Advanced tier only, and
  # metered, so it is behind a variable rather than on by default.
  dynamic "adaptive_protection_config" {
    for_each = var.enable_adaptive_protection ? [1] : []
    content {
      layer_7_ddos_defense_config {
        enable          = true
        rule_visibility = "STANDARD"
      }
    }
  }

  # -- 1000-1099: rate limiting -------------------------------------------

  # A ban rather than a throttle. The routes behind this run agent pipelines, so
  # a caller who has already exceeded a generous ceiling is not a user having a
  # busy moment; letting them straight back in at the limit lets them hold the
  # service at its maximum cost indefinitely.
  rule {
    action      = "rate_based_ban"
    priority    = 1000
    description = "Per-IP rate ban above a sustained burst."

    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }

    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"

      enforce_on_key = "IP"

      rate_limit_threshold {
        count        = var.rate_limit_requests
        interval_sec = var.rate_limit_interval_sec
      }

      ban_duration_sec = var.ban_duration_sec
    }
  }

  # A much tighter ceiling on the routes that each cost a model call. Priority
  # below the general rule so it is evaluated first.
  rule {
    action      = "rate_based_ban"
    priority    = 900
    description = "Tighter ban on the model-invoking and batch routes."

    match {
      expr {
        expression = join(" || ", [
          "request.path.matches('/api/v1/fraud/')",
          "request.path.matches('/api/v1/investigation/')",
          "request.path.matches('/api/v1/compliance/screen')",
          "request.path.matches('/api/v1/events/document')",
          "request.path.matches('/api/v1/simulate')",
          "request.path.matches('/deep-review')",
          "request.path.matches('/api/v1/ingest/')",
          "request.path.matches('/demo')",
        ])
      }
    }

    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"

      rate_limit_threshold {
        count        = var.expensive_route_requests
        interval_sec = 60
      }

      ban_duration_sec = var.ban_duration_sec
    }
  }

  # -- 2000-2099: OWASP preconfigured rules -------------------------------
  #
  # Sensitivity 1 throughout, deliberately. Higher sensitivities on these rule
  # sets produce false positives on ordinary JSON payloads, and this API accepts
  # shipping documents containing arbitrary text -- a cargo description is
  # exactly the sort of free text that trips an aggressive SQLi signature. A WAF
  # that blocks real shipments gets switched off, which is worse than one tuned
  # low.
  #
  # Note these are defence in depth, not the primary control: there is no SQL in
  # this system at all (Firestore), and the injection that actually threatens it
  # is prompt injection, which Model Armor and untrusted.py handle because no
  # WAF signature describes it.

  rule {
    action      = "deny(403)"
    priority    = 2000
    description = "OWASP SQL injection, low sensitivity."
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 2010
    description = "OWASP cross-site scripting, low sensitivity."
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 2020
    description = "Local file inclusion and path traversal."
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('lfi-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 2030
    description = "Remote code execution."
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('rce-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 2040
    description = "Scanner and vulnerability-probe detection."
    match {
      expr {
        expression = "evaluatePreconfiguredWaf('scannerdetection-v33-stable', {'sensitivity': 1})"
      }
    }
  }

  # -- 3000: optional geo restriction --------------------------------------
  #
  # Empty by default. Included because the application cannot express this at
  # all, not because a specific list is recommended -- a shipping compliance API
  # has legitimate counterparties in most countries, so blocking by geography is
  # a decision for whoever knows the customer base.
  dynamic "rule" {
    for_each = length(var.blocked_countries) > 0 ? [1] : []
    content {
      action      = "deny(403)"
      priority    = 3000
      description = "Country block list."
      match {
        expr {
          expression = join(" || ", [
            for c in var.blocked_countries : "origin.region_code == '${c}'"
          ])
        }
      }
    }
  }

  # -- 2147483647: default ------------------------------------------------
  #
  # Allow. The perimeter is not the authorisation boundary -- the API key and the
  # role floor are, and they live in the application where they can see who is
  # asking. A default-deny here would mean maintaining an IP allow-list for a
  # public API, which is not what this service is.
  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default: allow, and let the application authorise."
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}
