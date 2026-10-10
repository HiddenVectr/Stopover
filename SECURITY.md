# Security policy

## Reporting a vulnerability

Please report security issues **privately** through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** (direct link: <https://github.com/HiddenVectr/Baton/security/advisories/new>). Don't open a public issue for a vulnerability.

Include what you found, how to reproduce it, the Baton version or commit, and how you run it (Docker, Python, behind Tailscale or another proxy). You should get an acknowledgement within a week. Fixes are released as a new version with an advisory that credits you, unless you prefer not to be named.

## Supported versions

Baton is pre-1.0. Security fixes go into the **latest release only**; upgrade to get them. See [CHANGELOG.md](CHANGELOG.md) for each release's changes and upgrade notes.

## What Baton protects, and what it doesn't

Baton is built for one person or a trusted group on a private network. Please read this before reporting, so we agree on what counts as a vulnerability.

**Baton has no authentication.** Anyone who can reach the server can read and change every handoff and memory. Exposing it beyond your own machine or a restricted private network (such as Tailscale with access rules) is unsupported. Reports that an exposed server can be used by the people who reach it are expected behavior, not vulnerabilities.

**In scope:**

- Getting around the request checks: the `Host` allowlist (DNS-rebinding protection), `Origin` validation, Fetch Metadata rejection of cross-site browser requests, the 64 KiB body limit.
- A web page you visit being able to read or change Baton data through your browser.
- Script injection or other unsafe rendering in the dashboard.
- Data corruption, loss of claim fencing or retry safety, and escaping the data directory.
- Extension points (`create_app` hooks, authenticators) behaving differently from their documentation, in a way a host could rely on for security.

**Out of scope:**

- Anything requiring network access to a Baton server that wasn't restricted, as described above.
- What an AI agent does with content it reads from Baton (prompt injection through handoff text is a known risk; Baton marks stored text as task data, not instructions).
- Vulnerabilities in dependencies with no path to exploitation in Baton. Those are still welcome as regular issues or pull requests.
