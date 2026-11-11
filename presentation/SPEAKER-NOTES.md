# Speaker notes — Solace federal deck

These notes accompany the 10-slide deck. Press **N** in the browser to display them. The scenario is an unclassified **Launch detected** example used to walk through routing, access, and delivery. Timing is about **20–30 minutes** for the pitch and **5–10 minutes** for the demo at slide 8.

Recorded walkthroughs of the demo steps are on the repository Release and in `docs/DEMO-QUICK-REFERENCE.md`.

## Slide 01 — Get satellite alerts to the right people on the ground.

**What to show:** About 2 minutes. The problem on the title slide: the Publisher is in the cloud, and Ground 1 and Ground 2 run in a separate environment. A static bridge carries alerts across that boundary.

**Key points:** The challenge is getting each event to the right ground system — Ground 1 or Ground 2 — on time, only to authorized systems, without building another custom link for every new consumer.

**Where Solace adds value:** Event delivery from the Publisher, across the boundary, to Ground 1 and Ground 2.

**Likely questions:** Where do these events originate today, and where do the consumers that act on them run? How does an alert cross those environments today: a custom service, file transfer, or a manual step? Which separations are policy-driven, and which are network topology?

## Slide 02 — What we'll show today

**What to show:** About 2 minutes. Three outcomes you will see today: controlled access, reliable delivery, and less custom integration.

**Key points:** Controlled access: only approved people and systems receive the alert. A permitted consumer receives an event; unpermitted publish or subscribe attempts are denied. Reliable delivery: important alerts wait when an operator or system is offline. A display may tolerate a missed live update; an operations workflow may not. A service goes down; queued alerts are delivered when it reconnects. Less custom integration: new recipients can be added with subscription and access-rule changes, leaving the producer unchanged. Connector, authentication, and topic-mapping setup still exist; the aim is to avoid another custom link for each consumer.

**Where Solace adds value:** These three outcomes are what today's demo walks through.

**Likely questions:** What does on time mean for these consumers: seconds or minutes? Who approves which systems may see which events? Which consumers cannot tolerate a missed event? How long does onboarding a new consumer take today?

## Slide 03 — Every new recipient means another custom connection.

**What to show:** About 2 minutes. A typical pattern today: a Launch detected alert reaches Kafka over the ground link. Kafka keeps a retained log for history and analytics. Each ground application then builds its own path — app wiring A, B, and C — to the ops console, an analyst tool, and a ticket system.

**Key points:** Three integration pains show up on that path. App wiring: each new recipient needs another custom connection. Alert selection: each path has to choose which alerts it should see. Delivery and disconnect handling: each path has to handle an operator or system going offline. This is a typical pattern, not a claim about a specific customer architecture.

**Where Solace adds value:** The rest of the briefing shows a path that keeps Kafka for history and uses Solace to distribute matching alerts, so a new recipient does not require another custom connection.

**Likely questions:** How do new consumers get onboarded today, and how long does a new wiring path take? Who owns alert selection on each of those paths? Who handles delivery when an operator or system is offline?

## Slide 04 — A satellite has an alert. A person on the ground needs it.

**What to show:** About 2 minutes. The story on the slide: a satellite has an alert, a person on the ground needs it, and the seated operator reads Launch detected. Existing satellite communications stay in place; Solace starts after the feed is received.

**Key points:** Existing satellite communications and the ground link remain upstream. After the feed is received, the alert is delivered through a Solace Cloud broker, a static bridge across the boundary, and a ground broker, to the operator. Those two brokers and the bridge are the event mesh in this demo. Solace routes the alert to who needs it after the feed has been received.

**Where Solace adds value:** Downstream event delivery after the received feed: from the cloud broker, across the static bridge, to the ground broker and the operator who needs the alert.

**Likely questions:** Does Solace replace the ground station or satellite link? No; it starts after the feed is received. Why two brokers instead of one? Cloud and ground are separate environments; the static bridge carries only allowed topics across that boundary. Why not send alerts point to point? That is the problem on slide 3; slide 7 shows a Kafka-plus-Solace path.

## Slide 05 — The right alert reaches the right people.

**What to show:** About 2 minutes. A permitted operator receives Launch detected, and an unauthorized application is blocked.

**Key points:** Topics decide where an event goes. Access control decides who may publish or subscribe. A Solace topic is a string of levels in the message header, for example ssa/unclass/ground1/launch/25544/alert. The broker routes on the topic without reading the payload. Configuration covers queues, subscriptions, bridge subscriptions, and ACL profiles. ACL profiles have separate publish-topic and subscribe-topic controls, each a default action plus exceptions. Queue bind and consume permissions are reviewed separately.

**Where Solace adds value:** Topic routing and broker-enforced publish and subscribe permissions on the same path.

**Likely questions:** Does the broker read the payload? No, it routes on the topic in the message header. Can it default to deny? Yes, each ACL profile has a default action plus exceptions for publish and subscribe topics. Where are permissions managed? On the broker: ACL profiles assigned to client usernames, so apps don't enforce it themselves.

**Sources:** https://docs.solace.com/Security/Granting-Clients-Access.htm

## Slide 06 — Important alerts wait while a service is offline.

**What to show:** About 2 minutes. Two pictures. On the left, live updates use Direct messaging: if the service is offline, the update can be missed. On the right, important alerts wait in a queue and arrive when the service reconnects.

**Key points:** Queued means a durable endpoint on the ground broker holds the message while the subscriber is offline and the upstream bridge stays up. Capacity, acknowledgement, redelivery, and permissions are configured separately. Direct messaging delivers a live update while the consumer is subscribed. Guaranteed messaging retains the alert on a durable endpoint until it is consumed or expires, and delivery is acknowledged. An upstream link or bridge outage is a separate case: the ground broker can hold only what it has already received.

**Where Solace adds value:** Durable queues keep important alerts for an operator or system that is currently offline, within configured capacity and retention.

**Likely questions:** What if the queue fills up? Capacity is configured per queue; when full, the broker can reject new Guaranteed messages back to the publisher so nothing is lost silently. What if the bridge itself goes down? The ground broker holds only what it already received; that leg needs its own queue on the cloud side. Could the operator get a duplicate? Delivery is acknowledged; a message redelivered after a disconnect is flagged as redelivered so the app can handle it.

**Sources:** https://docs.solace.com/Get-Started/message-delivery-modes.htm

## Slide 07 — Keep Kafka for history. Let Solace distribute the alerts.

**What to show:** About 2 minutes. The alert reaches Kafka over the ground link. Kafka still keeps a retained log for history and analytics. A configured Kafka bridge feeds selected alerts into Solace, which routes matching alerts to the ground teams — the analyst tool, the ticket system, and the ops console. Kafka retains event history. Solace distributes alerts.

**Key points:** This is coexistence, not a replacement of Kafka. Kafka remains the system of record for history and analytics. The pattern can reduce per-application wiring for the same alert class, match which consumer needs which alert, and handle delivery when an operator or system is offline. Connector authentication, topic mapping, and operations still exist. Solace Kafka Bridging embeds a Kafka Receiver and Kafka Sender in the software event broker. Bootstrap addresses, authentication, TLS, topic bindings, and Solace topic mapping are configured.

**Where Solace adds value:** Distribution of matching alerts to ground teams, including disconnect handling, while Kafka remains the system of record for history and analytics.

**Likely questions:** Are you replacing Kafka? No — Kafka and Solace coexist. Kafka keeps history; Solace distributes matching alerts. Which paths need to stay on Kafka? Where does onboarding a new consumer take the most effort today: wiring, authorization, or offline delivery?

**Sources:** https://kafka.apache.org/documentation/; https://docs.solace.com/Features/Kafka-Bridging/Kafka-Bridging-Overview.htm

## Slide 08 — What you will see, one step at a time

**What to show:** About 1 minute on the map, then 5 to 10 minutes for the demo, returning to this map between demos. Events flow from the cloud broker to the ground broker, then to Ground 1 and Ground 2. The dashed line is the bridge: the ground side opens the connection outbound to the cloud. Two broker roles: a Solace Cloud service and a local software broker. The example topic is ssa/unclass/ground1/launch/25544/alert.

**Key points:** Routing: a publisher sends events toward Ground 1 and Ground 2. The example topic ssa/unclass/ground1/launch/25544/alert has six labeled levels: root, classification, site, category, object, and event. Topic wildcards select which events reach each consumer. In Solace topic subscriptions, * by itself matches exactly one level — any single value at that position. For example, ssa/unclass/*/launch/> matches a launch from any ground site. A * can also follow a prefix at that same level; for example, ground* matches ground, ground1, and ground2. The > wildcard, used by itself at the end of a subscription, matches one or more remaining levels — everything after that point. For example, ssa/unclass/ground1/*/25544/> matches every event for object 25544 at Ground 1. Compare those two subscriptions: launches from any site versus every event for object 25544 at Ground 1. Each subscriber shows only matching events. Access: a restricted client may publish and subscribe on an allowed prefix and is refused on a denied prefix. The broker's response is visible on the page and in Broker Manager. Delivery: send a guaranteed alert while a service is disconnected and the bridge stays up. The alert waits in a local durable queue and arrives tagged Queued when receiving resumes. A direct alert sent while disconnected does not appear after reconnect. Bonus — Demo 4, Operations Watch: an observer agent watches the existing Publisher and Operators. The primary operator is disconnected, alerts are sent, then it reconnects. Asked 'What happened overnight to the primary operator? Was anything missed?', Operations Watch reports the outage window and the queued alerts that were delivered. Demos 1–3 stand on their own. Click-by-click steps and recorded videos are in the repository Quick Reference.

**Where Solace adds value:** One topic path can serve different interests, enforce client permissions, and hold a guaranteed alert on a durable queue until the consumer is back.

**Likely questions:** Does * match more than one level? No. * matches a single level (either the whole level, or a prefix such as ground* at that level). > matches one or more trailing levels and only when it stands alone at the end. Who opens the bridge connection? The ground side connects outbound to the cloud, so no inbound port is needed on the ground. Is the AI needed for delivery? No; demos 1–3 stand alone.

**Sources:** https://docs.solace.com/Features/VPN/Message-VPN-Bridges.htm; https://docs.solace.com/Messaging/Wildcard-Charaters-Topic-Subs.htm

## Slide 09 — De-risking Agent Mesh in federal environments

**What to show:** About 3 minutes. Three federal AI-agent concerns, with proposed deployment controls and tests, after the core broker demo and Demo 4 (Operations Watch).

**Key points:** AI agent and data boundary: agents and data stay within the approved boundary. The boundary is the whole application — model, tools, external services, and storage — not only the model endpoint. Inventory outbound dependencies and verify actual data flows. Sensitive data and official records: conversations and generated files may be sensitive or may qualify as official records. Follow the customer-approved retention schedule, restrict access by designation or classification, and preserve legal holds with customer storage and records-management controls. Undo and conflicting changes: identify irreversible actions and require a human check before execution. Plan how to reverse or correct each action where possible, and test conflict handling and recovery after partial completion. Handling classified information would require an approved deployment with an Authorization to Operate (ATO) covering that classification level. This demonstration is unclassified.

**Where Solace adds value:** Agent Mesh lets you add an observing agent on the same guaranteed path, with customer controls for boundary, records, and irreversible actions.

**Likely questions:** Can it run on a private or local model? Yes. Solace Agent Mesh supports configurable LLM endpoints, including custom OpenAI-compatible endpoints through LiteLLM and self-hosted options such as Ollama. Does the agent change anything? No. In Demo 4, Operations Watch only observes: it uses read-only SEMP and a Direct subscription, does not publish, and does not consume from the operator's queue. Delivery in demos 1–3 does not depend on it. What about classified data? Classified use needs an approved deployment with an ATO at that level. This demo is unclassified.

**Sources:** https://docs.solace.com/Agent-Mesh/Framework/administering/backups-and-data-retention.htm

## Slide 10 — Prove the business value in your environment.

**What to show:** About 2 minutes. A short, staged pilot that proves three results, reusing today's demo path as Stage 1.

**Key points:** The pilot is meant to prove three results. Controlled access: allowed and denied attempts match the permission plan. Evidence: a test log and denial counts in Broker Manager. Delivery: validate expected delivery in planned outage cases. Evidence: queue depth and delivery counts in Broker Manager and Insights. Integration: add a recipient via subscriptions and access rules, with no producer changes, and document federal feasibility findings. Broker Manager and Insights give built-in messaging-layer monitoring (queue depth, consumers, clients, rates) that many programs build by hand in Grafana; they don't replace Grafana for app or business metrics, and Solace can feed Grafana via SEMP or a Prometheus exporter. Stage 1 reuses today's demo. Later stages run in your approved environment.

**Where Solace adds value:** A concrete way to connect controlled access, fewer missed important alerts, and less repeated integration effort to evidence in the customer's environment.

**Likely questions:** Does this replace our Grafana? No; Broker Manager and Insights cover the broker layer built in, and metrics can feed an existing Grafana via SEMP or a Prometheus exporter. Do producers change when we add a consumer? No; the new consumer gets a subscription and access rules. What does Stage 1 need? Reuse the demo path with the unclassified example.
