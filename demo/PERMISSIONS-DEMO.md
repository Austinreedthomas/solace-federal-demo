# Restricted client permissions

Demo 2 shows a Solace Cloud client whose ACL profile allows one topic prefix and denies the rest. The Restricted Operator page (`/restricted-operator`) exercises that client. The command-line tool `permissions_demo.py` can run the same three actions without the web pages.

## Broker setup

Create a client, for example `client-cloud-permissions-demo`, assigned to ACL profile `acl-cloud-permissions-demo`:

- Client Connect default action: Allow
- Publish default action: Disallow, with exception `solace-demo/permissions/allowed/>`
- Subscribe default action: Disallow, with the same exception

## Web page

Set `SOLACE_PERMISSIONS_DEMO=1` in the same environment as the split-client settings, plus the credentials for that restricted client (username, password, and a trust-store directory of CA PEMs). Point `SOLACE_PERMISSIONS_CONFIG` and `SOLACE_PERMISSIONS_TRUST_STORE` at those files if they are not in the default locations you choose.

Restart the web process so it loads the flag. The Restricted Operator page names the client and the broker; it does not display the host, password, or file path.

The buttons are:

1. **Connect, subscribe, and send** on `solace-demo/permissions/allowed/proof`. The client should receive its own message.
2. **Request the forbidden subscription** on `solace-demo/permissions/denied/proof`. The broker should refuse with **Subscription ACL Denied**.
3. **Try to publish to a forbidden topic** on the same denied prefix. The third button sends one persistent message so the broker must accept or reject it.

When the flag is off, the page says the restricted client is not turned on and the buttons stay disabled.

## Command-line tool

```bash
python permissions_demo.py allowed-send
python permissions_demo.py subscribe --topic solace-demo/permissions/denied/proof
python permissions_demo.py publish-guaranteed --topic solace-demo/permissions/denied/proof
```

`allowed-send` subscribes, publishes one new id, and waits for the message. A denial is reported when the SDK error contains `SOLCLIENT_SUBCODE_SUBSCRIPTION_ACL_DENIED` or `SOLCLIENT_SUBCODE_PUBLISH_ACL_DENIED`.

`SOLACE_PERMISSIONS_ALLOW_LOOPBACK=1` accepts a loopback host for a disposable local broker test. Certificate expiration and server-name checks stay on for remote `tcps://` hosts.

Optional evidence files can be written under a directory you set with `SOLACE_PERMISSIONS_EVIDENCE_DIR`. Passwords, the host, the VPN, and file paths are omitted from that output.
