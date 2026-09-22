/**
 * The Pub/Sub topics the pipeline publishes to.
 *
 * These two were documented in README.md from the start:
 *
 *     gcloud pubsub topics create shipment-events
 *     gcloud pubsub topics create case-decisions
 *
 * and on this project that step was simply never run. The consequence was not
 * loud: tools.publish_decision_direct catches every exception and records
 * `status="failed"` in the audit log rather than raising, which is the documented
 * "best effort" contract. So the final step of every single case failed with
 * `404 Resource not found (resource=case-decisions)` -- 40 out of 40 attempts --
 * and nothing surfaced it except reading the audit rows one by one.
 *
 * Declaring them here is the actual fix for that class of problem. A setup step
 * that lives only in a README is a step some environment will skip, and this one
 * did.
 *
 * DIFFERENT FROM THE REST OF THIS DIRECTORY: armor.tf and loadbalancer.tf
 * describe infrastructure that does not exist and is deliberately not applied,
 * for cost reasons. These two topics DO exist -- they were created imperatively
 * with gcloud to unblock the running pipeline. So if this directory is ever
 * applied, import them first rather than letting Terraform try to create what is
 * already there:
 *
 *     terraform import google_pubsub_topic.case_decisions case-decisions
 *     terraform import google_pubsub_topic.shipment_events shipment-events
 */

resource "google_pubsub_topic" "case_decisions" {
  project = var.project_id
  name    = var.decisions_topic

  # No subscription is declared, and that is intentional. Nothing in this system
  # consumes the topic; it exists so an external ERP/WMS/billing integration can
  # subscribe without the pipeline having to know about it. With no subscriber,
  # messages expire after the default retention and cost nothing to speak of.
  labels = {
    component = "pipeline"
    purpose   = "decision-egress"
  }
}

resource "google_pubsub_topic" "shipment_events" {
  project = var.project_id
  name    = var.events_topic

  # The ingress side, for a push subscription that would POST to
  # /api/v1/events/shipment. Referenced nowhere in src/ -- the deployed service
  # is driven by direct HTTP POSTs and WORKER_MODE=ondemand -- so this is here
  # for parity with the documented architecture rather than because anything
  # currently breaks without it.
  labels = {
    component = "pipeline"
    purpose   = "shipment-ingress"
  }
}
