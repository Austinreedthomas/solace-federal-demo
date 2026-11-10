# Simulated weather over MQTT

This example is off unless `SOLACE_MQTT_WEATHER=1`. The launch, access, and guaranteed demos do not depend on it.

A button on the Publisher page sends an HTTP request to the demo process. The process opens an MQTT connection and publishes one simulated reading at QoS 0. Solace carries MQTT QoS 0 as Direct. The operator, still an SMF subscriber, adds `ssa/unclass/ground1/weather/>` on the same session and shows the reading when that id arrives.

The topic is `ssa/unclass/ground1/weather/station-1/reading`. It is a simulated reading, separate from object 25544 and from the launch cards.

## Configuration

```text
SOLACE_MQTT_WEATHER=1
SOLACE_MQTT_URL=mqtts://<host>:<port>
SOLACE_MQTT_USERNAME=<client>
SOLACE_MQTT_PASSWORD=<secret>
SOLACE_MQTT_TRUST_FILE=<pem>
```

For Solace Cloud, copy the MQTT host and TLS port from that service's connection details. See [Default Port Numbers](https://docs.solace.com/Admin/Default-Port-Numbers.htm).

`mqtt://` is accepted only for `127.0.0.1`, `localhost`, or `::1`. Anywhere else requires `mqtts://` and `SOLACE_MQTT_TRUST_FILE` pointing at a PEM file. Certificate and hostname checks stay on. The URL must include the port and must not contain a username, password, path, or query.

Use a client that may publish `ssa/unclass/ground1/weather/>`. The local lab publisher can publish that prefix because its allow exception is `ssa/unclass/>`. Put Cloud MQTT settings in the same private env file you use for the split client, if you keep that file separate from `demo/.env`.

If the flag is on but the URL or client is missing, the other demos still start and the weather section reports what is missing.

QoS 1 is unused in this example (Solace carries MQTT QoS 1 as Guaranteed). The guaranteed topic tree `ssa-guaranteed/unclass/>` is unused here.
