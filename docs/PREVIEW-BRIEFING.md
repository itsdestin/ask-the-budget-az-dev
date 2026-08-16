# JLBC Insight — Preview Briefing

**For the three-person preview (admin, director, deputy director).** This is the short
version: install, the one-time admin setup, and how AI Mode spending is capped. It is
not the full Administrator Handbook.

**What this is.** A search-and-answer tool over the office's budget documents. It runs
on your own PC. Searching, browsing fiscal notes, and uploading documents work with no
account and cost nothing. **AI Mode** — which answers questions in plain English with
citations — is the only part that costs money, and it costs the office (not you) a few
cents per question.

---

## 1 · Install (each of the three PCs, once — about 5 minutes)

1. You'll get a zip file, `JLBC-Insight-<version>.zip`. **Copy it onto your own PC
   first** (Desktop is fine) — don't unzip it straight off the network drive, it's slow
   and sometimes stops halfway.
2. Right-click the zip → **Extract All…** → extract to
   `%LOCALAPPDATA%\JLBC-Insight`
   (paste that into the location box; it becomes `C:\Users\<you>\AppData\Local\JLBC-Insight`).
   Wait for it to finish — it's a large program.
3. Open that folder and double-click **`install.cmd`**.
4. When it asks for the **shared folder path**, paste the network path where the office
   corpus lives (your admin will give it to you — it looks like
   `\\server\share\jlbc-insight-data`). If you're not on the network yet, press Enter
   to skip — the app will ask for the path on its startup screen the first time you
   open it.
5. Done. Open **JLBC Insight** from your Desktop or Start Menu.

You do **not** need admin rights, and nothing else (Python, Java) has to be installed —
it's all inside the folder.

> **The one gotcha:** the shared-folder path must point at the folder that has the
> `lancedb` folder **inside** it — that's the actual corpus, one level down from the
> top of the shared folder. If you point at the parent, the app opens but shows no
> documents. If that happens you'll get a "can't start" screen with a box to fix the
> path; paste the deeper path.

---

## 2 · Set up the admin account (one PC, once — the admin does this)

The **admin** is the one person who can change the AI key, models, and spending limits.
Do this on the **admin's own PC**, first, before the others are configured:

1. Open the app, then the menu (top right) → **Settings**.
2. You'll see **"No admin is set up yet"** and a **"Claim admin as …"** button. Click it.
   That's the whole thing — your Windows username is now the admin, and the **Admin**
   page appears in the menu.

- This is **not a login or password** — the app just remembers your Windows username,
  matched exactly (`dmoss` and `DMOSS` count as different people). It keeps the Admin
  page from being browsed casually; it isn't security.
- Only one admin at a time. Everyone can see who the admin is on their own Settings page.
- **Locked out?** (admin left, or a username typo): in the shared data folder, create an
  empty text file named exactly **`RESET-ADMIN.txt`**. The next person to open Settings
  can then claim admin, and the file is used up so it only works once.

---

## 3 · Turn on AI Mode and cap the spending (the admin, once)

AI Mode sends the passages it retrieves to an outside AI provider to write the answer.
We use **OpenRouter** — one account, one bill, many AI models.

1. **Get a key:** create an account at **openrouter.ai**, add a small amount of credit,
   and under **Account → Keys** create a key (it starts `sk-or-v1-…`).
2. **Set the hard cap there:** on the OpenRouter account, set a **monthly credit limit**.
   This is the *real* ceiling — it's the only thing that stops spending outright, even if
   something in the app misbehaves.
3. **Put the key in the app:** in the app, menu → **Admin** → the **AI Mode** section →
   **Key** → **Add a key**, paste it, then click **Save** in the bar at the bottom.
   Every PC picks it up within a few seconds (it lives in the shared folder) — no
   restart needed.
4. **Choose models:** under **Standard** and **Deep Research**, pick a model from each
   one's recommended list (already chosen for cost/quality) and Save. Standard is the
   cheap everyday mode; Deep Research is the slower, pricier one.
5. **Set the in-app spending limits:** Admin → **AI Mode** → **Spending limits**:
   - **Each person, per month** — the default cap for everyone. Leave blank for no limit,
     `0` to block everyone.
   - **People with a different limit** — give the director / deputy director their own
     number. Use the Windows username shown on *their* Settings page, spelled and
     capitalized exactly.
   - **People with no limit at all** — e.g. the director; this beats any other limit.
   - Then **Save** (the bar at the bottom — nothing is saved until you click it).

**How the two caps fit together:** the in-app limits are per-person, per-calendar-month,
and stop that person's AI Mode questions at their number (searching keeps working for
everyone). The OpenRouter account cap is the office-wide hard stop. Use both. Each person
can watch their own month-to-date on their Settings page; the admin sees everyone under
Admin → **Spending → Who spent what**.

> **Reminder for everyone:** public-record documents only. Anything uploaded to the
> shared folder can be retrieved by an AI Mode question and sent to the outside AI
> provider — so never upload confidential material.

---

*Questions or it won't start? Send the newest file in
`%LOCALAPPDATA%\JLBC-Insight\logs` to whoever supports the app.*
