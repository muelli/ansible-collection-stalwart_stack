# Stalwart behind Caddy, in five Ansible roles

| Role | Does |
| --- | --- |
| `stalwart_install` | Pinned Stalwart server and `stalwart-cli` (sha256-checked, optional sigstore check), user, systemd unit, `config.json` (data store only), fallback admin |
| `caddy_front` | Caddy from the official build service (with DNS plugins), TLS for every web name, sites for Stalwart and other domains, certificate sync to Stalwart |
| `caddy_user_instances` | Socket-activated Caddy per user, reached by the front Caddy over a `0660` UNIX socket |
| `stalwart_config` | The declarative plan (listeners, DNS providers, certificates, domains, relays, sender routing) applied with `stalwart-cli apply` |
| `bulwark` | Bulwark webmail as a Podman Quadlet container, pointed at Stalwart's public URL (optional, `bulwark_enabled`) |

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
  `/run/caddy-user-sockets/alice.sock`. The hosts of a `caddy_user_instances`
  entry (`sites[].hosts`) get such a site automatically, so they only have to be
  listed once; a `caddy_domains` entry of the same name takes precedence (for
  `dns:` or other options). The DNS provider defaults to the site's `dns:`, else
  the one of the longest Stalwart domain the host lies below, else none
  (HTTP-01). An instance with `caddyfile:` and no `sites:` needs its hosts in
  `caddy_domains`. systemd creates that socket (mode
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
  automatic DNS would overwrite their SPF record. The role fails on that, unless
  the relay has `manages_spf: true` (it sends with its own return-path domain,
  as SMTP2GO does).
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

## Firewall

The roles do not touch the firewall (it differs per site). Open these TCP ports
on a host that runs them: 25, 465, 587 (SMTP), 143, 993 (IMAP), 4190
(ManageSieve), 80 and 443 (Caddy). With DebOps, put them into
`group_vars/mailservers/` of the DebOps inventory, as `ferm__dependent_rules`
(see `examples/ferm.example.yml`); that variable is not used by DebOps' own
mail roles, so it does not replace other rule lists.

## Bulwark webmail

The `bulwark` role runs the full Bulwark edition as a podman container through a
Quadlet unit (`/etc/containers/systemd/bulwark.container`), so systemd manages
it like a native service (`systemctl status bulwark`). It uses the host network,
listens on `127.0.0.1:3000`. The browser talks to Stalwart directly, so Bulwark
is pointed at `https://<stalwart_hostname>` (`bulwark_jmap_url`), never at the
loopback listener: the browser would try to reach `127.0.0.1` on its own
machine. Enable it with `bulwark_enabled: true` and `bulwark_admin_password`
(vault), then add a Caddy site:

```yaml
caddy_domains:
  - name: webmail.example.org
    dns: hetzner
    caddy_directive: |
      reverse_proxy 127.0.0.1:3000 {
          flush_interval -1
      }
```

### Automatic DNS for a subdomain of a zone

With `dns:` set Stalwart publishes the domain's records itself. It assumes the
domain is its own zone, so for `test.example.org` inside the zone `example.org`
the provider answers "Not found". Name the zone with `zone_origin`:

```yaml
stalwart_domains:
  - { name: test.example.org, state: present, dns: spaceship, zone_origin: example.org }
```

### Stalwart domains and Caddy sites are separate

Everything on the hostname of a `stalwart_domains` entry goes to Stalwart, through
its `http-proxy` listener with PROXY protocol v2 (the roles always create that
listener and the loopback `mgmt` listener, even when `stalwart_server_listeners`
is overridden). Stalwart serves many paths there (`/jmap`, `/dav`, `/auth`,
`/login`, `/.well-known/*`, `/autodiscover`, `/admin`, ...), its documentation
gives no list a front end could split on, and the list may grow, so a stalwart
entry has no `caddy_directive` and nothing else can be served on that name. Put
other sites into `caddy_domains`; the play fails when a name appears in both.

`/` on a Stalwart hostname is not served by Stalwart itself but redirected
(`Http.redirectRoot`, default `/account`). The roles point it at
`https://www.<first stalwart domain>/` (`stalwart_redirect_root`, which derives
from `stalwart_root_site`) and let Caddy answer there with its plain default
response, a site with no directives and no certificate of its own when a wildcard
covers it. Set `stalwart_redirect_root` to your own URL, or `stalwart_root_site: ""`
and `stalwart_redirect_root: ""` to leave both alone. After applying the plan the
role runs Stalwart's `ReloadSettings` action, since such settings are otherwise
read only at startup.

Each Stalwart domain gets one wildcard certificate (DNS-01, so it needs `dns:`;
Caddy 2.10 or newer, which prefers a wildcard certificate over per-name ones
when the config has one). The sites one label below the domain (`mta-sts`,
`autoconfig`, `autodiscover` and other `stalwart_domains` entries such as the
mail host) keep their own site files but get no certificate of their own, and
the copy for Stalwart's mail ports is taken from the wildcard certificate. The
domain itself keeps its own certificate, `caddy_domains` entries keep theirs,
and unknown subdomains get a 404 from the wildcard site. `wildcard: false` on an
entry gives every name its own certificate.

```yaml
stalwart_domains:
  - { name: test.example.org, state: present, dns: spaceship, zone_origin: example.org }
  - { name: mail.test.example.org, state: present }
```

### Web applications

`stalwart_applications` creates Stalwart `Application` objects: a zip bundle that
Stalwart downloads and serves under a URL prefix, next to its own `/admin` and
`/account`. After the plan is applied the roles run the `UpdateApps` action so
the bundle is fetched at once. Stalwart only accepts a single path segment as
prefix (`/app`, not `/` or `/a/b`), so an application cannot take over `/`; that
is what `stalwart_redirect_root` is for.

```yaml
stalwart_applications:
  - description: Some app
    url_prefix: [/app]
    resource_url: https://example.org/app.zip
```

### Browser apps and CORS

CORS has no parent-domain rule: a browser compares the exact origin
(`https://webmail.example.org`), so `example.org` does not cover its subdomains.
List the origins of browser apps such as Bulwark in `stalwart_cors_origins`
(`caddy_front`). Caddy then answers the preflight and sets
`Access-Control-Allow-Origin` for those origins only, replacing what Stalwart
adds, and sends no CORS headers to any other origin. Stalwart's own
`Http.usePermissiveCors` (all origins) stays off (`stalwart_permissive_cors`).

## Removing things

* Entries of `stalwart_domains`, `stalwart_relay_hosts`,
  `stalwart_server_listeners` and `caddy_user_instances` accept
  `state: absent`. Files, systemd units, certificates, group memberships and the
  objects inside Stalwart (domain, its DKIM keys, certificate, relay, listener)
  are removed. `stalwart_absent_dns_providers` removes DNS providers.
* The default domain cannot be removed. `SystemSettings.defaultDomainId` points
  to `stalwart_default_domain`, which is the first `present` entry of
  `stalwart_domains` (it is not derived from `stalwart_hostname`, which only
  sets the default hostname). Stalwart also refuses to delete a domain that
  still has accounts. To remove the default domain, put another present entry
  first and run, delete the domain's accounts (the roles do not manage
  accounts: `stalwart-cli delete Account --ids <id>`), then mark the domain
  `absent` and run again.
* Removing a domain does not remove the DNS records Stalwart published for it.
  Delete them at the provider yourself. Recreating the domain publishes the
  full set again, provided `zone_origin` is right.
* Whole roles: `stalwart_install_state`, `caddy_front_state`, `bulwark_state`
  set to `absent`. Data stays unless `stalwart_purge_data`, `caddy_purge_data`
  or `bulwark_purge_data` is true. A `caddy_user_instances` entry can add
  `purge: true` and `release_linger: true`.
* `teardown.yml` removes everything in reverse order:
  `ansible-playbook teardown.yml -e stalwart_purge_data=true ...`

## Tested

Ubuntu 26.04 VM, ansible-core 2.21.5, Stalwart 1.0.0 (fresh install) and 1.0.2
(upgrade from 1.0.1, repeat run without changes), stalwart-cli 1.0.14, Bulwark
1.20.0 (upgrade from 1.18.0; its readiness check cannot reach Stalwart on the
VM, which has an internal CA), Caddy with its internal CA: fresh install, repeat run without changes,
fallback to recovery, forced apply through the management listener, web path
Caddy -> Stalwart (PROXY v2) and Caddy -> user socket -> user Caddy, socket
unreachable for other users, certificate sync and reload.
xcaddy build via podman (cache hit on the second run, plugin present in the
binary) and the DebOps group check.
Also tested: Bulwark as a Quadlet container behind Caddy, `state: absent` for
domains, relays, listeners and per-user instances, the full teardown with purge
and a fresh reinstall (second run changed nothing).
Also tested: `stalwart_applications` (create, update, `state: absent`, repeat
runs), origin-restricted CORS for Bulwark, sites derived from
`caddy_user_instances`, and on a real host: webmail login at Bulwark, a user
Caddy site with a DNS-01 certificate from Spaceship.
Not tested: push notifications (Stalwart to the Bulwark push relay), relays and
sender routing against real servers, other distributions than Ubuntu 26.04.

## Installing from Galaxy

The roles ship as the collection `muelli.stalwart_stack`:

```bash
ansible-galaxy collection install muelli.stalwart_stack
ansible-playbook -i inventory/hosts.ini muelli.stalwart_stack.site
ansible-playbook -i inventory/hosts.ini muelli.stalwart_stack.teardown
```

Roles are also usable by their FQCN, for example
`muelli.stalwart_stack.caddy_front`. Cloning the repository still works with
`playbook.yml` and `teardown.yml`, which use the short role names. Version
0.1.0 is a pre-release, see `CHANGELOG.md`.

### Releasing

Bump `version` in `galaxy.yml`, add a `## <version>` section to `CHANGELOG.md`,
commit, then `git tag v<version> && git push origin v<version>`. The Release
workflow runs the tests, builds, publishes to Galaxy and creates a GitHub
release. It needs the repository secret `GALAXY_API_KEY`.

## Tests

`tests/run.sh` needs no target host: it syntax-checks `playbook.yml` and
`teardown.yml`, parses every YAML file and template, runs the derivation of
Caddy sites from `caddy_user_instances` (`tests/user_instance_sites.yml`) with
the hosts listed once, twice and with a differing explicit entry, and runs
`ansible-lint` when installed (`var-naming` and `yaml` style rules are skipped).
Everything else was tested by hand on a VM, see above.

## License

GPL-3.0-or-later. See `LICENSE`.
