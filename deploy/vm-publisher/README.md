# Publisher service (example)

This systemd unit serves only the Publisher page. It is a starting point for running `python -m solace_demo web` on a host on your network. Edit the paths, user, and bind address to match that host.

The example layout is:

- Application tree (this repository's `demo/` directory, including `.venv`): `/home/ubuntu/solace-publisher/app`
- Environment file (mode `0600`): `/home/ubuntu/solace-publisher/publisher.env`
- Unit file: `solace-publisher.service`

```bash
sudo install -m 0600 publisher.env /home/ubuntu/solace-publisher/publisher.env
sudo cp solace-publisher.service /etc/systemd/system/solace-publisher.service
sudo systemctl daemon-reload
sudo systemctl enable --now solace-publisher.service
systemctl status solace-publisher.service
```

`publisher.env` should set `SOLACE_WEB_ROLE=publisher`, `SOLACE_WEB_HOST` to the address you want the page bound on, `SOLACE_WEB_PORT`, and the Solace Cloud publisher variables listed in [demo/README.md](../../demo/README.md) and [demo/SPLIT-CLIENT.md](../../demo/SPLIT-CLIENT.md). Leave `SOLACE_OPERATOR_*` and `SOLACE_PERMISSIONS_*` unset in this file.

Open `http://<host>:<port>/publisher`.
