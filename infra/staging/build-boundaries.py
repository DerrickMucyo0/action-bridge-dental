#!/usr/bin/env python3
"""Build public, unapplied per-function boundary drafts. No AWS or private inputs."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESTINATIONS = ("us-east-1", "us-east-2", "us-west-2")
MODEL = "amazon.nova-2-lite-v1:0"


def statement(sid, actions, resources, condition=None):
    item = {"Sid": sid, "Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        item["Condition"] = condition
    return item


def boundaries(manifest):
    if (manifest["account"], manifest["region"], manifest["stack_name"]) != ("631367363628", "us-east-2", "actionbridge-dental-staging"):
        raise ValueError("Boundary drafts are restricted to the reviewed staging target")
    if set(manifest["functions"]) != {"HealthFunction", "CasesFunction", "CalculationsFunction", "JobsFunction", "JobWorkerFunction"}:
        raise ValueError("Boundary drafts require the five reviewed functions")
    account, region = manifest["account"], manifest["region"]
    table = f"arn:aws:dynamodb:{region}:{account}:table/{manifest['table']['name']}"
    uploads = f"arn:aws:s3:::{manifest['buckets']['uploads']}/uploads/*"
    queue = f"arn:aws:sqs:{region}:{account}:{manifest['queues']['work']}"
    profile = f"arn:aws:bedrock:{region}:{account}:inference-profile/us.{MODEL}"
    models = [f"arn:aws:bedrock:{destination}::foundation-model/{MODEL}" for destination in DESTINATIONS]
    ohio = {"StringEquals": {"aws:RequestedRegion": region}}
    owned = {"StringEquals": {"s3:ResourceAccount": account}}
    result = {}
    for logical, function in manifest["functions"].items():
        log_streams = f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{function['name']}:log-stream:*"
        allow = [statement("OwnLogStreams", ["logs:CreateLogStream", "logs:PutLogEvents"], log_streams)]
        if logical == "CasesFunction":
            allow.append(statement("StagingCases", ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem", "dynamodb:Query"], table))
        elif logical == "CalculationsFunction":
            allow.append(statement("ReadStagingCase", ["dynamodb:GetItem"], table))
        elif logical in ("JobsFunction", "JobWorkerFunction"):
            allow.append(statement("StagingJobs", ["dynamodb:GetItem", "dynamodb:PutItem"], table))
        if logical == "JobsFunction":
            allow += [
                statement("QuotaKeysOnly", ["dynamodb:UpdateItem"], table, {
                    "ForAllValues:StringLike": {"dynamodb:LeadingKeys": ["STAGING_QUOTA#*"]},
                    "Null": {"dynamodb:LeadingKeys": "false"},
                }),
                statement("EnqueueStagingWork", ["sqs:SendMessage"], queue),
                statement("PresignStagingUploads", ["s3:PutObject"], uploads, owned),
                statement("SpeechInConfiguredRegion", ["polly:SynthesizeSpeech"], "*", {"StringEquals": {"aws:RequestedRegion": "us-east-1"}}),
            ]
        if logical == "JobWorkerFunction":
            allow += [
                statement("PollStagingWork", ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], queue),
                statement("ReadAndRemoveStagingUploads", ["s3:GetObject", "s3:DeleteObject"], uploads, owned),
                statement("ChosenNovaProfile", ["bedrock:InvokeModel"], profile, ohio),
                statement("NovaThroughChosenProfileOnly", ["bedrock:InvokeModel"], models, {"StringEquals": {"bedrock:InferenceProfileArn": profile}}),
                statement("OwnTranscriptionJobs", ["transcribe:GetTranscriptionJob", "transcribe:DeleteTranscriptionJob"],
                          f"arn:aws:transcribe:{region}:{account}:transcription-job/actionbridge-{manifest['stack_name']}_*"),
                statement("RegionalDocumentAndAudioProcessing", ["transcribe:StartTranscriptionJob", "textract:DetectDocumentText", "textract:StartDocumentTextDetection", "textract:GetDocumentTextDetection"], "*", ohio),
            ]
        # Explicit denies also constrain resource-policy grants to role sessions.
        # They do not invent resource scoping for APIs whose resource is '*'.
        by_action = {}
        for item in allow:
            resources = item["Resource"] if isinstance(item["Resource"], list) else [item["Resource"]]
            for action in item["Action"]:
                by_action.setdefault(action, set()).update(resources)
        deny = [{"Sid": "NoOtherActions", "Effect": "Deny", "NotAction": sorted(by_action), "Resource": "*"}]
        grouped = {}
        for action, resources in by_action.items():
            if "*" not in resources:
                grouped.setdefault(tuple(sorted(resources)), []).append(action)
        for index, (resources, actions) in enumerate(sorted(grouped.items())):
            deny.append({"Sid": f"NoOtherResources{index}", "Effect": "Deny", "Action": sorted(actions), "NotResource": list(resources)})
        for index, item in enumerate(allow):
            equals = item.get("Condition", {}).get("StringEquals", {})
            for key, value in equals.items():
                deny.append({"Sid": f"RequireContext{index}{len(deny)}", "Effect": "Deny", "Action": item["Action"],
                             "Resource": item["Resource"], "Condition": {"StringNotEquals": {key: value}}})
        if logical == "JobsFunction":
            deny += [
                {"Sid": "NoOtherQuotaKeys", "Effect": "Deny", "Action": "dynamodb:UpdateItem", "Resource": table,
                 "Condition": {"ForAnyValue:StringNotLike": {"dynamodb:LeadingKeys": ["STAGING_QUOTA#*"]}}},
                {"Sid": "QuotaKeysMustBePresent", "Effect": "Deny", "Action": "dynamodb:UpdateItem", "Resource": table,
                 "Condition": {"Null": {"dynamodb:LeadingKeys": "true"}}},
            ]
        result[function["boundary_policy_name"]] = {"Version": "2012-10-17", "Statement": allow + deny}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare public drafts without writing anything")
    args = parser.parse_args()
    generated = HERE / "generated"
    manifest = json.loads((HERE / "resources.json").read_text())
    for name, document in boundaries(manifest).items():
        if len(json.dumps(document, separators=(",", ":"))) > 6144:
            raise SystemExit("Boundary exceeds IAM managed-policy size limit: " + name)
        path = generated / (name + ".json")
        content = json.dumps(document, indent=2) + "\n"
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise SystemExit("Public boundary draft is out of date: " + path.name)
        else:
            generated.mkdir(exist_ok=True)
            path.write_text(content)
    print("Five public boundary drafts are current. No AWS/private-file access.")


if __name__ == "__main__":
    main()
