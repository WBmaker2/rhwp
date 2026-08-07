from __future__ import annotations

import copy
import unittest

from scripts.staging_infrastructure_approval import (
    InfrastructureApprovalError,
    validate_infrastructure_approval,
)
from scripts.staging_infrastructure_plan import build_infrastructure_plan
from scripts.tests.test_staging_infrastructure_approval import (
    approval_fixture,
    plan_bytes,
)
from scripts.tests.test_staging_infrastructure_plan import (
    approved_record as bootstrap_approval_record,
    manifest_and_packet,
    packet_text_and_digest,
)


class SafeSecretValuesDeclarationTest(unittest.TestCase):
    def test_rejects_nested_or_spelled_variant_safe_secret_declarations(self) -> None:
        manifest, packet = manifest_and_packet()
        _, packet_digest = packet_text_and_digest(packet)
        plan = build_infrastructure_plan(
            manifest,
            packet,
            bootstrap_approval_record(packet, packet_digest),
            packet_digest,
        )

        cases = (
            (
                "flattened root dotted key",
                lambda candidate: candidate.__setitem__(
                    "security.secretValuesIncluded", False
                ),
            ),
            (
                "nested location",
                lambda candidate: candidate["security"].__setitem__(
                    "nested", {"secretValuesIncluded": False}
                ),
            ),
            (
                "dotted nested key",
                lambda candidate: candidate["security"].__setitem__(
                    "nested.secretValuesIncluded", False
                ),
            ),
            ("snake case", lambda candidate: candidate["security"].__setitem__("secret_values_included", False)),
            ("kebab case", lambda candidate: candidate["security"].__setitem__("secret-values-included", False)),
            ("lower case", lambda candidate: candidate["security"].__setitem__("secretvaluesincluded", False)),
            ("different secret key", lambda candidate: candidate["security"].__setitem__("secretValue", False)),
            ("different token key", lambda candidate: candidate["security"].__setitem__("accessToken", False)),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                candidate_plan = copy.deepcopy(plan)
                mutate(candidate_plan)
                candidate_raw = plan_bytes(candidate_plan)
                candidate_approval = approval_fixture(candidate_plan, candidate_raw)
                with self.assertRaisesRegex(InfrastructureApprovalError, "sensitive"):
                    validate_infrastructure_approval(
                        candidate_plan,
                        candidate_raw,
                        candidate_approval,
                        require_cloud_mutation=False,
                    )
