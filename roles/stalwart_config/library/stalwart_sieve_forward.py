#!/usr/bin/python
# -*- coding: utf-8 -*-
# GNU General Public License v3.0+

DOCUMENTATION = r"""
---
module: stalwart_sieve_forward
short_description: Manage one named Sieve script of a Stalwart account through the management API
description:
  - Uploads the script as the administrator (JMAP SieveScript, no password of the account needed),
    activates it, and compares the content first, so an unchanged script is not touched.
  - Activating a script deactivates the account's other scripts; they are kept.
options:
  url: {description: "URL of the management listener, for example http://127.0.0.1:8081.", required: true, type: str}
  user: {description: "Administrator.", required: true, type: str}
  password: {description: "Administrator's password.", required: true, type: str}
  account_id: {description: "Id of the account.", required: true, type: str}
  name: {description: "Name of the script.", default: stalwart-forward, type: str}
  content: {description: "Sieve source. Required for state=present.", type: str}
  state: {description: "absent deactivates and deletes the script.", choices: [present, absent], default: present, type: str}
author: muelli.stalwart_stack
"""

import base64
import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url

USING = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:sieve"]


class Api:
    def __init__(self, url, user, password):
        self.url = url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()

    def _open(self, url, data=None, ctype="application/json", method=None):
        r = open_url(url, data=data, method=method or ("POST" if data is not None else "GET"),
                     headers={"Authorization": self.auth, "Content-Type": ctype},
                     force_basic_auth=False, timeout=30)
        return r.read()

    def call(self, *calls):
        body = json.dumps({"using": USING, "methodCalls": [[n, a, str(i)] for i, (n, a) in enumerate(calls)]})
        res = json.loads(self._open(self.url + "/jmap", body.encode()))
        out = []
        for name, args, _ in res["methodResponses"]:
            if name == "error":
                raise RuntimeError("%s: %s" % (args.get("type"), args.get("description")))
            out.append(args)
        return out

    def upload(self, account, content):
        r = json.loads(self._open("%s/jmap/upload/%s/" % (self.url, account), content.encode(), "application/sieve"))
        return r["blobId"]

    def download(self, account, blob):
        return self._open("%s/jmap/download/%s/%s/script.sieve" % (self.url, account, blob)).decode()


def main():
    m = AnsibleModule(
        argument_spec=dict(
            url=dict(type="str", required=True),
            user=dict(type="str", required=True),
            password=dict(type="str", required=True, no_log=True),
            account_id=dict(type="str", required=True),
            name=dict(type="str", default="stalwart-forward"),
            content=dict(type="str"),
            state=dict(type="str", default="present", choices=["present", "absent"]),
        ),
        required_if=[("state", "present", ["content"])],
        supports_check_mode=True,
    )
    p = m.params
    api = Api(p["url"], p["user"], p["password"])
    acc = p["account_id"]
    try:
        got = api.call(("SieveScript/get", {"accountId": acc, "properties": ["name", "isActive", "blobId"]}))[0]
        cur = next((s for s in got["list"] if s["name"] == p["name"]), None)

        if p["state"] == "absent":
            if cur is None:
                m.exit_json(changed=False)
            if not m.check_mode:
                if cur["isActive"]:
                    r = api.call(("SieveScript/set", {"accountId": acc, "update": {cur["id"]: {"isActive": False}}}))[0]
                    if r.get("notUpdated"):
                        m.fail_json(msg="deactivating the script failed: %s" % json.dumps(r["notUpdated"]))
                r = api.call(("SieveScript/set", {"accountId": acc, "destroy": [cur["id"]]}))[0]
                if r.get("notDestroyed"):
                    m.fail_json(msg="deleting the script failed: %s" % json.dumps(r["notDestroyed"]))
            m.exit_json(changed=True)

        want = p["content"]
        if cur is not None and cur["isActive"] and api.download(acc, cur["blobId"]) == want:
            m.exit_json(changed=False)
        if m.check_mode:
            m.exit_json(changed=True)
        blob = api.upload(acc, want)
        if cur is None:
            args = {"accountId": acc, "create": {"s": {"name": p["name"], "blobId": blob}}, "onSuccessActivateScript": "#s"}
        else:
            args = {"accountId": acc, "update": {cur["id"]: {"blobId": blob}}, "onSuccessActivateScript": cur["id"]}
        r = api.call(("SieveScript/set", args))[0]
        bad = r.get("notCreated") or r.get("notUpdated")
        if bad:
            m.fail_json(msg="the script was rejected: %s" % json.dumps(bad))
        m.exit_json(changed=True)
    except Exception as e:  # network, auth, unexpected response
        m.fail_json(msg="Stalwart management API: %s" % e)


if __name__ == "__main__":
    main()
