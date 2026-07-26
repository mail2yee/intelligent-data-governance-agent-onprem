"""
On-prem Camunda 8 (self-managed) integration - STUB, not wired yet.

Need before implementing for real:
  - The self-managed cluster's Zeebe gateway address (CAMUNDA_GATEWAY_ADDRESS
    in .env is a placeholder).
  - Whatever auth the on-prem cluster requires (self-managed Camunda 8 is
    often unauthenticated on a trusted internal network, unlike Camunda
    SaaS's OAuth client-credentials flow - confirm which applies here).
  - The deployed BPMN process ID this should start (the GCP PoC used
    "data-gov-approval" as a placeholder that was never actually
    deployed to a real Camunda process - confirm the real process id/
    definition once one exists).

Self-managed Camunda 8 exposes a gRPC Zeebe gateway, not a REST API like
the SaaS product's public endpoint - the recommended client is the
`pyzeebe` library rather than hand-rolled HTTP calls. Add `pyzeebe` to
requirements.txt when implementing this for real.
"""


async def start_approval_process(
    ticket_id: str, products: list[str], owners: list[str], purpose: str
) -> str:
    """Returns a human-readable status string for display/logging.

    TODO: replace with a real pyzeebe `ZeebeClient.run_process()` call
    once gateway address, auth, and process id are confirmed.
    """
    return "Skipped (Camunda self-managed integration not yet implemented)"
