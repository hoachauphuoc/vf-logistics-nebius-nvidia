/**
 * The global external Application Load Balancer that hosts the Cloud Armor
 * policy in armor.tf.
 *
 * NOT APPLIED -- see the header in armor.tf for why.
 *
 * Cloud Armor cannot be attached to a Cloud Run service directly. It attaches to
 * a backend service, which requires a serverless network endpoint group, which
 * requires a load balancer. That chain is the entire reason this file exists and
 * the entire reason the feature costs money: the policy itself is cheap, the
 * load balancer in front of it is not.
 */

# ---------------------------------------------------------------------------
# Serverless NEGs -- one per Cloud Run service
# ---------------------------------------------------------------------------

resource "google_compute_region_network_endpoint_group" "backend" {
  name                  = "vf-logistics-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = var.backend_service_name
  }
}

resource "google_compute_region_network_endpoint_group" "console" {
  name                  = "vf-console-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region

  cloud_run {
    service = var.console_service_name
  }
}

# ---------------------------------------------------------------------------
# Backend services -- where the security policy actually attaches
# ---------------------------------------------------------------------------

resource "google_compute_backend_service" "backend" {
  name                  = "vf-logistics-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  # The attachment point. Everything else in this file exists to make this line
  # possible.
  security_policy = google_compute_security_policy.vf_logistics.id

  backend {
    group = google_compute_region_network_endpoint_group.backend.id
  }

  # Sampled rather than complete: full logging on a polled dashboard API is a
  # meaningful log bill, and 10% is enough to see an attack pattern. Raise it
  # while investigating an incident.
  log_config {
    enable      = true
    sample_rate = 0.1
  }
}

resource "google_compute_backend_service" "console" {
  name                  = "vf-console-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  security_policy       = google_compute_security_policy.vf_logistics.id

  backend {
    group = google_compute_region_network_endpoint_group.console.id
  }

  log_config {
    enable      = true
    sample_rate = 0.1
  }
}

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

resource "google_compute_url_map" "main" {
  name = "vf-logistics-urlmap"

  # The console is the front door; the API is reached under /api and a few
  # service paths. This mirrors what the application already does -- the backend
  # redirects "/" to CONSOLE_URL -- so the LB does not introduce a second,
  # different idea of where the root is.
  default_service = google_compute_backend_service.console.id

  host_rule {
    hosts        = [var.domain]
    path_matcher = "main"
  }

  path_matcher {
    name            = "main"
    default_service = google_compute_backend_service.console.id

    path_rule {
      paths   = ["/api/*", "/health", "/metrics", "/agents", "/legacy"]
      service = google_compute_backend_service.backend.id
    }
  }
}

resource "google_compute_managed_ssl_certificate" "main" {
  name = "vf-logistics-cert"

  managed {
    domains = [var.domain]
  }
}

resource "google_compute_target_https_proxy" "main" {
  name             = "vf-logistics-https-proxy"
  url_map          = google_compute_url_map.main.id
  ssl_certificates = [google_compute_managed_ssl_certificate.main.id]
}

resource "google_compute_global_address" "main" {
  name = "vf-logistics-ip"
}

resource "google_compute_global_forwarding_rule" "https" {
  name                  = "vf-logistics-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
  target                = google_compute_target_https_proxy.main.id
  ip_address            = google_compute_global_address.main.id
}

# Plain HTTP exists only to redirect. Serving the API over it would undo the HSTS
# header the application now sets.
resource "google_compute_url_map" "redirect" {
  name = "vf-logistics-http-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  name    = "vf-logistics-http-proxy"
  url_map = google_compute_url_map.redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  name                  = "vf-logistics-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "80"
  target                = google_compute_target_http_proxy.redirect.id
  ip_address            = google_compute_global_address.main.id
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "load_balancer_ip" {
  value       = google_compute_global_address.main.address
  description = "Point the domain's A record here."
}

output "ingress_lockdown_command" {
  description = <<-EOT
    Run this AFTER the load balancer is serving traffic and the certificate is
    ACTIVE. Until it runs, the *.run.app URLs still answer directly and every
    rule in armor.tf is bypassable by addressing them -- which is the failure
    mode that makes a WAF look like it is working when it is not.
  EOT
  value = join("\n", [
    for svc in [var.backend_service_name, var.console_service_name] :
    "gcloud run services update ${svc} --region=${var.region} --ingress=internal-and-cloud-load-balancing"
  ])
}
