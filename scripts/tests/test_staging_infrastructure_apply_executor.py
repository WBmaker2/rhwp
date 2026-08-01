from __future__ import annotations
import base64, copy, hashlib, json, os, subprocess, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch
from scripts.staging_infrastructure_actions import build_execution_manifest
from scripts.staging_infrastructure_apply_ready import build_apply_ready_package
from scripts.staging_infrastructure_apply_review import build_apply_review_package
from scripts.staging_infrastructure_apply_review_policy import (
    GITHUB_OIDC_ISSUER, wif_attribute_mapping, wif_expected_condition, wif_expected_principal,
)
from scripts.staging_infrastructure_operator_attestation import (
    ATTESTATION_ENCODING, ENVIRONMENT_ATTESTATION_SCHEMA,
    ENVIRONMENT_QUERY_CONTRACT, WIF_ATTESTATION_SCHEMA, WIF_QUERY_CONTRACT,
    MAX_ATTESTATION_TTL, _issue_fixed_query_attestation,
    environment_required_contract, utc_text,
)
from scripts.staging_infrastructure_apply_approval import DECLARATION_SCHEMA, MutationApprovalError, bind_run_approval, validate_apply_ready_package, validate_mutation_approval, validate_mutation_approval_declaration
from scripts.staging_infrastructure_apply_executor import ApplyExecutionError, execute_approved_actions
from scripts.staging_infrastructure_apply_provenance import ProvenanceError, validate_pre_auth_provenance
from scripts.staging_infrastructure_apply_prepare import ApplyPrepareError, prepare_run_bound_evidence
from scripts.staging_infrastructure_synthetic_fixture import canonical_plan_and_approval
from scripts.staging_infrastructure_operator_attestation import canonical_attestation_bytes
from scripts.staging_infrastructure_operator_signature import signed_attestation_sha256

COMMIT, TREE, CONTENT = "a" * 40, "b" * 40, "c" * 64
_KEY_DIRECTORY = None
_PRIVATE_KEY = None
_REGISTRY_PATCH = None


def test_operator_signing_key():
 global _KEY_DIRECTORY, _PRIVATE_KEY, _REGISTRY_PATCH
 if _PRIVATE_KEY is None:
  _KEY_DIRECTORY=tempfile.TemporaryDirectory(); root=Path(_KEY_DIRECTORY.name); _PRIVATE_KEY=root/"operator-private.pem"; public=root/"operator-public.pem"
  subprocess.run(["openssl","genpkey","-algorithm","ED25519","-out",str(_PRIVATE_KEY)],check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); os.chmod(_PRIVATE_KEY,0o600)
  subprocess.run(["openssl","pkey","-in",str(_PRIVATE_KEY),"-pubout","-out",str(public)],check=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  public_pem=public.read_text(); registry=MappingProxyType({"synthetic-operator":MappingProxyType({"algorithm":"ed25519","publicKeyPem":public_pem,"publicKeySha256":hashlib.sha256(public_pem.encode()).hexdigest()})})
  _REGISTRY_PATCH=patch("scripts.staging_infrastructure_operator_signature.TRUSTED_OPERATOR_KEY_REGISTRY",registry); _REGISTRY_PATCH.start()
 return _PRIVATE_KEY

class ApplyExecutorTest(unittest.TestCase):
 def setUp(self):
  plan, result, raw = canonical_plan_and_approval(); execution = build_execution_manifest(plan, result, plan_bytes=raw)
  self.review = build_apply_review_package(plan, result, execution, plan_bytes=raw, executor_commit_sha=COMMIT)
  self.now = datetime.now(timezone.utc).replace(microsecond=0)
  contract = environment_required_contract()
  self.environment = {"schemaVersion":ENVIRONMENT_ATTESTATION_SCHEMA,"queryContractVersion":ENVIRONMENT_QUERY_CONTRACT,"status":"verified","verified":True,"encoding":ATTESTATION_ENCODING,"environmentName":"staging-infrastructure-apply","repository":"WBmaker2/rhwp","repositoryId":"11","repositoryOwnerId":"22","environmentId":"33","requiredContract":contract,"observed":{"requiredReviewerCount":1,"preventSelfReview":False,"canAdminsBypass":False,"deploymentBranchPolicy":contract["deploymentBranchPolicy"],"variableNames":contract["variableNames"]},"responseDigests":{"repository":"d"*64,"environment":"e"*64,"branchPolicyPages":["f"*64],"variablePages":["a"*64]},"observedAt":utc_text(self.now),"expiresAt":utc_text(self.now+MAX_ATTESTATION_TTL)}
  provider = "projects/123/locations/global/workloadIdentityPools/staging-pool/providers/staging-provider"; service = "deployer-staging@rhwp-collaboration-staging-123.iam.gserviceaccount.com"; expected = {"attributeMapping":wif_attribute_mapping(),"attributeCondition":wif_expected_condition("11","22",COMMIT),"workloadIdentityUserPrincipal":wif_expected_principal(provider,"11"),"workloadIdentityUserRole":"roles/iam.workloadIdentityUser","oidcIssuerUri":GITHUB_OIDC_ISSUER,"allowedAudienceMode":"default-provider-resource"}
  self.wif = {"schemaVersion":WIF_ATTESTATION_SCHEMA,"queryContractVersion":WIF_QUERY_CONTRACT,"status":"verified","verified":True,"encoding":ATTESTATION_ENCODING,"projectId":self.review["projectId"],"providerResourceName":provider,"serviceAccount":service,"repositoryId":"11","repositoryOwnerId":"22","ref":"refs/heads/feat/firebase-collaboration-mvp-v1","workflowRef":"WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1","workflowSha":COMMIT,"expected":expected,"observed":{"providerResourceName":provider,"providerState":"ACTIVE","providerDisabled":False,"attributeMappingMatches":True,"attributeConditionMatches":True,"workloadIdentityUserBindingMatches":True,"oidcIssuerMatches":True,"allowedAudienceMode":"default-provider-resource"},"observedResourceProvenance":{"providerResourceName":provider,"serviceAccount":service},"responseDigests":{"provider":"b"*64,"serviceAccountIamPolicy":"c"*64},"observedAt":utc_text(self.now),"expiresAt":utc_text(self.now+MAX_ATTESTATION_TTL)}
  review_raw = json.dumps(self.review, ensure_ascii=False, indent=2).encode()+b"\n"; self.package = build_apply_ready_package(self.review, review_raw, _issue_fixed_query_attestation(self.environment), _issue_fixed_query_attestation(self.wif), operator_signing_key_id="synthetic-operator", operator_signing_private_key=test_operator_signing_key(), now=self.now)
  self.raw = json.dumps(self.package, ensure_ascii=False, indent=2).encode()+b"\n"
  self.approval = {"schemaVersion":"rhwp.staging-infrastructure-mutation-approval/v3","decision":"approved","approvedAt":utc_text(self.now),"approvedBy":["synthetic-human"],"expiresAt":utc_text(self.now+timedelta(minutes=10)),"approvalNonce":"N"*24,"approvedRunId":"123456","approvedRunAttempt":1,"applyReadyPackageSha256":hashlib.sha256(self.raw).hexdigest(),"environmentAttestationSha256":self.package["environmentAttestationSha256"],"wifAttestationSha256":self.package["wifAttestationSha256"],"planSha256":self.review["sourceEvidence"]["planSha256"],"planObjectSha256":self.review["sourceEvidence"]["planObjectSha256"],"executorCommitSha":COMMIT,"projectId":self.review["projectId"],"approvedStageIds":["api-baseline","service-accounts","artifact-registry","secret-metadata"],"approvedActionIds":[x["actionId"] for x in self.review["canonicalMutationSubset"]],"environmentSpecReviewed":True,"wifIdentityReviewed":True,"leastPrivilegeIamDiffReviewed":True,"rollbackReviewed":True,"cloudMutationApproved":True,"deploymentApproved":False}
 def approved(self): return validate_mutation_approval(self.package,self.raw,self.approval,now=self.now)
 def test_prepare_declaration_binds_only_current_run(self):
  declaration=copy.deepcopy(self.approval); declaration.pop("approvedRunId"); declaration.pop("approvedRunAttempt"); declaration["schemaVersion"]=DECLARATION_SCHEMA
  self.assertEqual(validate_mutation_approval_declaration(self.package,self.raw,declaration,now=self.now)["schemaVersion"],DECLARATION_SCHEMA)
  bound=bind_run_approval(self.package,self.raw,declaration,run_id="777777",run_attempt=2,now=self.now)
  self.assertEqual(bound["approvedRunId"],"777777"); self.assertEqual(bound["approvedRunAttempt"],2)
  with self.assertRaises(MutationApprovalError): bind_run_approval(self.package,self.raw,declaration,run_id="0",run_attempt=2,now=self.now)
  with self.assertRaises(MutationApprovalError): validate_mutation_approval(self.package,self.raw,declaration,now=self.now)
 def test_prepare_cli_preserves_package_bytes_and_rejects_sha_mismatch(self):
  declaration=copy.deepcopy(self.approval); declaration.pop("approvedRunId"); declaration.pop("approvedRunAttempt"); declaration["schemaVersion"]=DECLARATION_SCHEMA
  with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
   root=Path(directory); package_b64=root/"package.b64"; declaration_b64=root/"declaration.b64"; package_out=root/"package.json"; approval_out=root/"approval.json"
   package_b64.write_bytes(base64.b64encode(self.raw)); declaration_b64.write_bytes(base64.b64encode(json.dumps(declaration,separators=(",", ":")).encode()))
   result=prepare_run_bound_evidence(package_b64,declaration_b64,expected_package_sha256=hashlib.sha256(self.raw).hexdigest(),run_id="456789",run_attempt=3,package_output=package_out,approval_output=approval_out,now=self.now)
   self.assertEqual(result["runId"],"456789"); self.assertEqual(package_out.read_bytes(),self.raw)
   bound=json.loads(approval_out.read_text()); self.assertEqual(bound["approvedRunId"],"456789"); self.assertEqual(bound["approvedRunAttempt"],3)
   bad_out=root/"bad-package.json"
   with self.assertRaises(ApplyPrepareError): prepare_run_bound_evidence(package_b64,declaration_b64,expected_package_sha256="0"*64,run_id="456789",run_attempt=3,package_output=bad_out,approval_output=root/"bad-approval.json",now=self.now)
   self.assertFalse(bad_out.exists())
 def claims(self):
  return {"packageSha256":hashlib.sha256(self.raw).hexdigest(),"executorCommitSha":COMMIT,"executorTreeSha":TREE,"expectedExecutorTreeSha":TREE,"repository":"WBmaker2/rhwp","expectedRepository":"WBmaker2/rhwp","repositoryId":"11","expectedRepositoryId":"11","repositoryOwnerId":"22","expectedRepositoryOwnerId":"22","ref":"refs/heads/feat/firebase-collaboration-mvp-v1","expectedRef":"refs/heads/feat/firebase-collaboration-mvp-v1","workflowRef":"WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1","expectedWorkflowRef":"WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1","workflowSha":COMMIT,"expectedWorkflowSha":COMMIT,"workflowContentSha256":CONTENT,"expectedWorkflowContentSha256":CONTENT,"runId":"123456","runAttempt":1,"artifactSourceRunId":"123456","artifactId":"666","artifactName":"staging-infrastructure-approved-evidence","artifactArchiveSha256":CONTENT,"artifactSourceCommitSha":COMMIT}
 def test_review_package_cannot_be_approved_without_apply_ready_promotion(self):
   with self.assertRaises(MutationApprovalError): validate_mutation_approval(self.review, json.dumps(self.review).encode(), self.approval, now=self.now)
 def test_v3_approval_binds_live_attestations_and_time(self):
  self.assertTrue(self.approved()["cloudMutationApproved"])
  for key,value in (("approvalNonce","x"),("approvedAt",utc_text(self.now-timedelta(seconds=1))),("environmentAttestationSha256","d"*64),("token","bad")):
   changed=copy.deepcopy(self.approval); changed[key]=value
   with self.assertRaises(MutationApprovalError): validate_mutation_approval(self.package,self.raw,changed,now=self.now)
  forged=copy.deepcopy(self.package); payload=forged["environmentAttestation"]["payload"]; payload["responseDigests"]["repository"]="0"*64; forged["environmentAttestation"]["payloadSha256"]=hashlib.sha256(canonical_attestation_bytes(payload)).hexdigest(); forged["environmentAttestationSha256"]=signed_attestation_sha256(forged["environmentAttestation"])
  with self.assertRaises(MutationApprovalError): validate_apply_ready_package(forged,now=self.now)
 def test_provenance_compares_actual_and_protected_values(self):
  approved,claims=self.approved(),self.claims(); self.assertEqual(validate_pre_auth_provenance(self.package,approved,claims,now=self.now),claims)
  for field,value in (("repositoryId","999"),("workflowSha","d"*40),("executorCommitSha","d"*40),("artifactSourceCommitSha","d"*40),("runAttempt",2)):
   altered=dict(claims); altered[field]=value
   with self.assertRaises(ProvenanceError): validate_pre_auth_provenance(self.package,approved,altered,now=self.now)
 def test_apply_requires_matching_live_attestation_and_is_durable_noop_on_replay(self):
  approved,claims=self.approved(),self.claims(); state={x["actionId"]:"missing" for x in self.review["canonicalMutationSubset"]}; writes=[]
  def observe(action):
   current=state[action["actionId"]]; return {"state":current,"resourceKind":action["resourceKind"],"matchesDesired":current == "present"}
  def write(argv): writes.append(argv); state[self.review["canonicalMutationSubset"][len(writes)-1]["actionId"]]="present"; return "ok"
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   with self.assertRaises(ApplyExecutionError): execute_approved_actions(self.package,approved,claims,root/"a",root/"b",apply=True,runner=write,git_binding_validator=lambda *_:None)
   execute_approved_actions(self.package,approved,claims,root/"plan",root/"post",apply=True,observer=observe,runner=write,git_binding_validator=lambda *_:None)
   self.assertEqual(len(writes),len(state))
   execute_approved_actions(self.package,approved,claims,root/"plan2",root/"post2",apply=True,observer=observe,runner=write,git_binding_validator=lambda *_:None)
   self.assertEqual(len(writes),len(state)); self.assertIn("applyReadyPackageSha256",json.loads((root/"plan2").read_text())["approvalBinding"])
 def test_postcondition_evidence_marks_successful_write_then_failure(self):
  approved,claims=self.approved(),self.claims(); calls=0
  def observe(action):
   nonlocal calls; calls += 1
   if calls == 1: return {"state":"missing","resourceKind":action["resourceKind"],"matchesDesired":False}
   return {"state":"incompatible","resourceKind":action["resourceKind"],"matchesDesired":False}
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory)
   with self.assertRaises(ApplyExecutionError): execute_approved_actions(self.package,approved,claims,root/"plan",root/"post",apply=True,observer=observe,runner=lambda _:"ok",git_binding_validator=lambda *_:None)
   evidence=json.loads((root/"post").read_text()); self.assertEqual(evidence["writeAttemptedActionId"],self.review["canonicalMutationSubset"][0]["actionId"]); self.assertTrue(evidence["writeReturnedSuccess"]); self.assertEqual(evidence["postconditionStatus"],"incompatible")
 def test_workflow_contract_uses_live_attestation_and_pinned_actions(self):
  text=(Path(__file__).resolve().parents[2]/".github/workflows/staging-infrastructure-apply.yml").read_text()
  self.assertNotIn("getEnvironment",text); self.assertNotIn("/environments/{environment_name}/variables",text); self.assertNotIn("STAGING_APPROVED_APPLY_READY_PACKAGE_JSON",text); self.assertNotIn("STAGING_APPROVED_MUTATION_APPROVAL_JSON",text); self.assertIn("STAGING_APPLY_READY_PACKAGE_B64",text); self.assertIn("STAGING_MUTATION_APPROVAL_DECLARATION_B64",text); self.assertIn("needs: prepare",text); self.assertIn("EXPECTED_PROJECT_ID",text); self.assertNotIn("--provenance-validated",text); self.assertNotIn("--environment-attestation",text)
  prepare=text.split("  apply:",1)[0]; apply=text.split("  apply:",1)[1]
  self.assertNotIn("environment: staging-infrastructure-apply",prepare); self.assertIn("id-token: none",prepare); self.assertIn("id-token: write",apply); self.assertLess(text.index("Prepare exact run-bound evidence"),text.index("google-github-actions/auth@")); self.assertNotIn("STAGING_APPLY_READY_PACKAGE_B64",apply)
  for pin in ("actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093","actions/upload-artifact@65462800fd760344b1a7b4382951275a0abb4808","actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd","google-github-actions/setup-gcloud@6a7c903a70c8625ed6700fa299f5ddb4ca6022e9"):
   self.assertIn(pin,text)
