# Stalwart behind Caddy, in four Ansible roles

| Role | Does |
| --- | --- |
| `stalwart_install` | Pinned Stalwart server and `stalwart-cli` (sha256-checked, optional sigstore check), user, systemd unit, `config.json` (data store only), fallback admin |
| `caddy_front` | Caddy from the official build service (with DNS plugins), TLS for every web name, sites for Stalwart and other domains, certificate sync to Stalwart |
| `caddy_user_instances` | Socket-activated Caddy per user, reached by the front Caddy over a `0660` UNIX socket |
| `stalwart_config` | The declarative plan (listeners, DNS providers, certificates, domains, relays, sender routing) applied with `stalwart-cli apply` |

Run order is fixed (`playbook.yml`): install, front Caddy (it must obtain the
certificates the plan references), user instances, then the plan.

## Use

```
cp examples/hosts.example.ini inventory/hosts.ini           # inventory/ is git-ignored
cp examples/group_vars-all.example.yml inventory/group_vars/all.yml
ansible-vault encrypt_string ...                             # secrets go in a vault
ansible-playbook -i inventory/hosts.ini playbook.yml
```

Needs ansible-core >= 2.16 on the controller; the target is Debian or Ubuntu
on x86_64 or aarch64 with systemd.

## How the pieces fit

* Caddy owns ports 80 and 443 and every certificate (DNS-01 per provider, or
  Caddy's internal CA with `caddy_tls_mode: internal` for tests).
* Stalwart's web side (admin UI, JMAP, webmail) listens on `127.0.0.1:8008`
  and expects PROXY protocol v2 from Caddy. Mail ports (25, 465, 587, 143, 993,
  4190) are served by Stalwart directly with the certificate Caddy obtained.
  `stalwart-cert-sync@<domain>.path` copies a renewed certificate to
  `/etc/stalwart/certs` and asks Stalwart to reload it.
* `caddy_domains` entries with `user: alice` are forwarded to
  `/run/caddy-user-sockets/alice.sock`. systemd creates that socket (mode
  `0660`, group `alice`; the front Caddy joins the group). The first request
  starts `systemd-socket-proxyd`, which starts alice's Caddy; both stop after
  `caddy_user_idle_time` without traffic.
* Stalwart is configured only through `stalwart-cli apply`. The first apply runs
  against a temporary recovery instance, later ones against a loopback-only
  listener (`127.0.0.1:8081`), falling back to recovery if that fails.
  Re-applying happens when the rendered plan changes, or with
  `-e stalwart_force_apply=true`.

## Things to know

* Written for Stalwart 1.0.x. Object fields differ from 0.16 (`Relay.host`,
  `NetworkListener.implicitTls`); the CLI has to match the server version.
* Port 80/443 must be free. `caddy_front` refuses to start Caddy otherwise (for
  example when DebOps runs Apache or nginx on the same host).
* `stalwart_conflicting_services` (default empty) lists units to stop and
  disable first, for example `[apache2, postfix, dovecot, rspamd, opendkim]`.
  On a DebOps-managed host the next `debops run` would start them again, so the
  play fails when the host is still in the matching `debops_service_*` group
  (`stalwart_check_debops_groups: false` turns that off). Use the nested groups
  of `examples/hosts.example.ini`: moving a host between `with_stalwart` and
  `without_stalwart` is the only edit needed.
* The Stalwart unit conflicts with `postfix`, `sendmail` and `exim4`.
* The plan contains DNS and relay secrets; it is written `0600` and hidden from
  Ansible output. The fallback admin password (>= 12 characters) is required.
* Domains with a relay in `sender_domain_routing` must not set `dns:`;
  automatic DNS would overwrite their SPF record. The role fails on that.
* `caddy_user_instances` expects the accounts to exist (DebOps can create them).
* New Stalwart or CLI versions need their sha256 in `stalwart_checksums` /
  `stalwart_cli_checksums`, or set `stalwart_checksum` / `stalwart_cli_checksum`.
* `caddy_build_method` is `download` (build service, no checksum), `xcaddy` or
  `binary` (prebuilt file plus `caddy_binary_sha256`).
* `xcaddy` builds on the controller and caches the result in
  `caddy_build_cache_dir` (default `.cache/caddy`, keyed by version, modules and
  architecture). By default it runs the official `caddy:<ver>-builder` image
  with `podman run --rm`, so the controller needs only podman; the pulled image
  stays in podman's storage unless `caddy_builder_remove_image: true`. With
  `caddy_xcaddy_runner: local` it uses `xcaddy` from PATH. Entries of
  `caddy_xcaddy_modules` / `caddy_xcaddy_replaces` are the arguments of
  `--with` / `--replace`. When you pin `caddy_xcaddy_caddy_version`, pin the
  modules too: a new plugin release can require a newer Caddy and the build
  fails.

## Tested

Ubuntu 26.04 VM, ansible-core 2.21.5, Stalwart 1.0.0, stalwart-cli 1.0.14,
Caddy with its internal CA: fresh install, repeat run without changes,
fallback to recovery, forced apply through the management listener, web path
Caddy -> Stalwart (PROXY v2) and Caddy -> user socket -> user Caddy, socket
unreachable for other users, certificate sync and reload.
xcaddy build via podman (cache hit on the second run, plugin present in the
binary) and the DebOps group check.
Not tested: DNS-01 against real providers and automatic DNS management.

## License

GPL-3.0-or-later. See `LICENSE`.
