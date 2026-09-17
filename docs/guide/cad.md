# CAD incident feeds

ToneWatch can subscribe to the versioned JSON contract published by
[icad2mqtt](https://github.com/JustBeanie/icad2mqtt). Configure a CAD feed with
an MQTT host (or an existing MQTT alert target), its base topic (normally
`911/cad`), and the feed's correlation windows. The retained incidents
snapshot is authoritative; transition events fill the gaps between snapshots.

CAD payloads are untrusted. ToneWatch validates the schema, timestamps,
string lengths, incident count, and payload size before storing anything.

Incident addresses and cross streets are stored in SQLite and follow the call
retention policy. Use broker ACLs so only the ToneWatch subscriber can read
the CAD topics, and restrict access to the ToneWatch API and database.

Enrichment notifications use the existing alert dispatcher. Webhook and MQTT
targets opt in by adding `call_enriched` to their event list. Meshtastic
targets opt in by adding it to `phases`; CAD type and address are sent to the
mesh only when the configured template explicitly uses `{cad_type}` or
`{cad_address}`. Home Assistant discovery exposes those two fields as event
attributes on the call entity.
