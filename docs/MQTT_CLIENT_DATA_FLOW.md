# MQTT client data flow

This document describes what a client application must publish and what happens to the message between the MQTT broker, local durable storage, and Amazon S3.

## Executive summary

```text
Client application
  -> MQTT v5 PUBLISH to app/<SEN>/<site>/<topic...>
  -> MQTT broker
  -> fsu-mqtt subscription app/# (QoS 1)
  -> validate topic and create archive envelope
  -> append one JSON object plus newline to a local .jsonl.part file
  -> fsync the record to local storage
  -> acknowledge broker delivery
  -> finalize the batch as .jsonl
  -> upload the finalized file to S3
  -> delete the local file only after PutObject succeeds
```

The archive provides **at-least-once collection for QoS 1**, not exactly-once delivery. Clients that need event-level deduplication should publish a stable MQTT v5 user property named `event_id`.

> A `PUBACK` received by the publishing client confirms the broker accepted its QoS 1 publish. It does **not** confirm that the archive service has written the message or uploaded it to S3. The archive service's later acknowledgment is between the service and the broker.

## Client publishing contract

### MQTT protocol and QoS

- Use MQTT v5.
- Publish with **QoS 1** for messages that must be archived reliably.
- QoS 0 messages can be collected, but have no broker redelivery guarantee and should be treated as best effort.
- The service subscription is granted at QoS 1, so the archive contract is at-least-once rather than exactly-once.
- Retained publications are accepted and the original retain flag is recorded. Retained state can be delivered again when the broker creates a new subscription, for example after session loss or expiry.

### Topic

Publish to:

```text
app/<SEN>/<site>/<topic...>
```

Example:

```text
app/123/SiteA/status/device-1
```

| Part                | Requirement                         | Archived value                                 |
|---------------------|-------------------------------------|------------------------------------------------|
| `app`               | Fixed literal                       | Included in `topic`                            |
| `SEN`               | Positive decimal integer            | Numeric `sen`, for example `123`               |
| `site`              | Non-empty site identifier           | String `site`, for example `SiteA`             |
| `topic...`          | One or more non-empty path segments | Full `subtopic`, for example `status/device-1` |
| First topic segment | Identifies the message type         | `base_topic`, for example `status`             |

Do not publish topics containing MQTT wildcards (`+` or `#`), null bytes, invalid UTF-8, empty path segments, or whitespace-only site/topic segments. Use a canonical SEN without leading zeros even though the receiver parses SEN numerically.

All valid topics under `app/#` are archived. The archive service does not filter messages to one configured SEN or site.

### Event identity

Add this MQTT v5 user property when downstream systems need to recognize broker redelivery or application retries:

```text
event_id = <producer-generated-event-identifier>
```

The publisher should:

1. Generate an `event_id` for each logical event.
2. Keep it unchanged whenever that same event is retried.
3. Make it unique within `(SEN, site, subtopic)`.
4. Use a new ID for a distinct event, even if its payload is identical.

The property is optional and copied verbatim to JSONL. The service does not synthesize it from the payload, MQTT packet ID, or DUP flag.

The archive also generates `id`, but that is a **receipt ID**, not a producer event ID. A broker redelivery can therefore produce two records with different `id` values and the same `event_id`. Consumers should deduplicate identified events using:

```text
(sen, site, subtopic, event_id)
```

Messages without `event_id` remain valid, but consumers cannot reliably distinguish a redelivery from a separate event with the same payload.

### Payload

The payload is kept opaque; no application payload schema is currently imposed:

- Valid UTF-8 bytes are stored unchanged as the JSON string `value`.
- Invalid UTF-8/binary bytes are Base64 encoded in `value` and the record includes `"encoding":"base64"`.
- An empty payload is valid and is stored as `"value":""`.
- `received_at` is the archive service's UTC receipt time, not a publisher event timestamp. Put event time inside the payload if the application requires it.

## Archive record format

Each received message becomes one JSON object on one line of a JSONL/NDJSON file.

Example for a UTF-8 payload:

```json
{"id":"9fa32d15-ec4e-4d19-b4ea-f302722ddb31","topic":"app/123/SiteA/status/device-1","sen":123,"site":"SiteA","subtopic":"status/device-1","base_topic":"status","event_id":"producer-event-42","value":"online","received_at":"2026-09-02T10:11:12Z","qos":1,"retained":false}
```

Example for the binary bytes `ff 00 fe`:

```json
{"id":"e62aa924-ca68-4ff8-a134-2d2706b415ba","topic":"app/123/SiteA/raw","sen":123,"site":"SiteA","subtopic":"raw","base_topic":"raw","value":"/wD+","encoding":"base64","received_at":"2026-09-02T10:11:12Z","qos":1,"retained":false}
```

| Field         | Type               | Meaning                                                                             |
|---------------|--------------------|-------------------------------------------------------------------------------------|
| `id`          | string (UUID)      | Unique archived receipt; changes if the broker redelivers the message               |
| `topic`       | string             | Complete original MQTT topic                                                        |
| `sen`         | integer            | SEN parsed from the topic                                                           |
| `site`        | string             | Site parsed from the topic                                                          |
| `subtopic`    | string             | Everything after `app/<SEN>/<site>/`                                                |
| `base_topic`  | string             | First segment of `subtopic`                                                         |
| `event_id`    | string, optional   | Publisher's MQTT v5 `event_id` user property                                        |
| `value`       | string             | Original UTF-8 payload or Base64 text                                               |
| `encoding`    | string, optional   | Present as `base64` only for a non-UTF-8 payload                                    |
| `received_at` | RFC 3339 timestamp | Time the archive service received the broker delivery, normalized to UTC            |
| `qos`         | integer            | QoS of the delivery received by the archive service                                 |
| `retained`    | boolean            | Original MQTT retain flag                                                           |
| `data`        | object, optional   | Server-side topic-specific enrichment; no custom enrichment is currently registered |

Clients should tolerate optional fields being absent and additional `data` fields being introduced later.

## Collection and acknowledgment sequence

For every broker delivery, the service:

1. Receives messages through its `app/#` subscription.
2. Validates and parses the topic.
3. Copies the payload and MQTT metadata into the archive envelope.
4. Generates a receipt UUID in `id`.
5. Appends the record and newline to the active local `.jsonl.part` batch.
6. Calls `fsync` for the record before acknowledging a QoS 1 delivery to the broker.
7. Finalizes the batch by syncing, closing, and atomically renaming it from `.jsonl.part` to `.jsonl`.

If the local append or sync fails, the service does not acknowledge the delivery and stops, allowing a persistent broker session to redeliver an unacknowledged QoS 1 message after recovery.

A message with an invalid topic, or one rejected by future custom validation, is logged and acknowledged without being archived. Publishers must therefore follow the topic contract; broker acceptance alone does not prove application-level validity.

The archive uses a stable MQTT client ID, a non-clean initial connection, and a non-zero session expiry (default 24 hours). These settings let the broker retain unacknowledged QoS 1 deliveries across ordinary reconnects, subject to broker configuration and the session not expiring.

## Local batching and crash recovery

Files are partitioned by the record's service receipt hour in UTC:

```text
<local_path>/year=YYYY/month=MM/day=DD/hour=HH/<timestamp>-<uuid>.jsonl
```

Example:

```text
/monitoring/mqtt/year=2026/month=09/day=02/hour=10/20260902T101112.000000000Z-<uuid>.jsonl
```

The active file has an extra `.part` suffix and is not eligible for upload. It is finalized when any of these occurs:

- `batch_size` records have been appended (default `1000`);
- `batch_interval` seconds elapse (default `60`);
- a message belongs to a different UTC hour;
- the service shuts down cleanly.

On startup, interrupted `.jsonl.part` files are recovered. An incomplete trailing JSONL line is truncated, while all complete, potentially acknowledged lines are retained. A non-empty recovered file is then finalized to `.jsonl`.

In `local` storage mode, finalized files remain under `local_path` and are not sent to S3.

## S3 delivery

In `s3` storage mode, `local_path` remains a required durable spool. The service never streams an active message directly to S3.

Only finalized `.jsonl` files are selected. For each file, the S3 object key is:

```text
<prefix>/<path relative to local_path>
```

For example, with bucket `example-archive`, prefix `mqtt`, and the file above:

```text
s3://example-archive/mqtt/year=2026/month=09/day=02/hour=10/20260902T101112.000000000Z-<uuid>.jsonl
```

Objects are uploaded with:

```text
Content-Type: application/x-ndjson
```

Pending-file scans happen:

- when the upload worker starts, so files left from an earlier run are retried;
- after each configured batch interval;
- once more during graceful shutdown, within the available shutdown deadline.

A `PutObject` failure leaves the finalized local file in place for a later scan. The local file is removed only after `PutObject` succeeds. If S3 succeeded but local deletion did not, the same path can be uploaded again to the same object key on a later scan.

Consequences for consumers:

- S3 arrival is asynchronous and eventual; there is no per-message S3 acknowledgment to the publisher.
- Do not assume object arrival order across batches or retries. Use record fields such as `received_at` and application event metadata instead.
- An active `.jsonl.part` file is intentionally invisible to S3 until rotation.
- The durable local spool needs enough disk capacity for an S3 outage.

The service uses the AWS SDK default credential chain. S3 mode requires a configured AWS region and bucket; the prefix is optional.

## Recommended publisher checklist

- [ ] Connect using MQTT v5 and the broker credentials supplied for the deployment.
- [ ] Publish to `app/<positive-SEN>/<non-empty-site>/<non-empty-topic...>`.
- [ ] Use QoS 1 for reliable archiving.
- [ ] Attach a stable, producer-generated `event_id` user property when deduplication matters.
- [ ] Reuse the same `event_id` for retries of the same event; never infer identity from payload equality.
- [ ] Put producer event time and any domain schema inside the payload when needed.
- [ ] Treat publisher `PUBACK` as broker acceptance, not local-archive or S3 confirmation.
- [ ] Expect at-least-once records and make downstream processing idempotent.

## Relevant implementation

- Topic parsing and JSONL envelope: `internal/fsu-hypercare/mqtt/handler.go`
- MQTT connection, event property extraction, persistence, and acknowledgment: `internal/fsu-hypercare/mqtt/main.go`
- Subscription behavior: `internal/fsu-hypercare/mqtt/subscribe.go`
- Local batching and recovery: `internal/fsu-hypercare/mqtt/writer.go`
- S3 key construction and upload: `internal/fsu-hypercare/mqtt/s3.go`
- Upload scheduling and shutdown: `internal/fsu-hypercare/mqtt/upload_worker.go`
- Configuration defaults and validation: `internal/fsu-hypercare/shared/config_mqtt.go`

