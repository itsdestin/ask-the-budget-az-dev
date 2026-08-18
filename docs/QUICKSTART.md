# JLBC Search — Quick Start

One page. If you can double-click a file, you can install this. It needs no admin
rights and nothing already installed on your PC.

---

## 1. Install it (about 5 minutes)

**The easy way — the one-click installer.** On the USB drive, double-click
**`Install-JLBC-Search.cmd`** (it sits next to the zip). It asks for two folders and
does everything else itself:

1. **Install folder** — where the program lives. Press **Enter** to take the
   recommended spot (`%LOCALAPPDATA%\JLBC-Search`).
2. **Shared data folder** — where the budget documents live. **Drag the folder into
   the window and press Enter**, or paste its path. This is the folder that has the
   **`lancedb`** folder inside it (the search index). Press Enter alone to set it
   later from inside the app.

When it finishes you have a **JLBC Search** icon on your Desktop and in the Start
Menu.

**The manual way** (if you ever need it): copy `JLBC-Search-<version>.zip` to your own
PC, right-click → **Extract All…** → extract to `%LOCALAPPDATA%\JLBC-Search`, open that
folder, and double-click **`install.cmd`**.

> **The one gotcha:** the shared-data path must point at the folder that has the
> `lancedb` folder **inside** it — that is the actual corpus, one level down. Point at
> the parent and the app opens but shows no documents. If that happens you'll get a
> "can't start" screen with a box to fix the path.

> **If Windows shows a blue "Windows protected your PC" box:** click **More info**,
> then **Run anyway**. That box appears for any program that has not been bought a
> code-signing certificate; it is not a virus warning.

---

## 2. Start it

Double-click the **JLBC Search** icon. The first start takes 20–40 seconds while it
loads its search models; after that it is a few seconds.

You can now **search the budget documents and read fiscal notes**. That works with no
accounts, no keys, and no internet connection.

Closing the window does not shut the app down — clicking the icon again brings it
straight back.

---

## 3. Set up the admin account (one PC, once — the admin does this)

The **admin** is the one person who can change the AI key, models, and spending limits.
Do this on the **admin's own PC**, first, before the others are configured:

1. Open the app, then the menu (top right) → **Settings**.
2. You'll see **"No admin is set up yet"** and a **"Claim admin as …"** button. Click
   it. Your Windows username is now the admin, and the **Admin** page appears in the
   menu.

- This is **not a login or password** — the app just remembers your Windows username,
  matched exactly (`dmoss` and `DMOSS` count as different people). It keeps the Admin
  page from being browsed casually; it isn't security.
- Only one admin at a time. Everyone can see who the admin is on their own Settings
  page.

---

## 4. Turn on AI Mode and cap the spending (the admin, once)

AI Mode answers questions in sentences instead of returning documents. It is the only
part that costs money. It sends the passages it retrieves to an outside AI provider —
we use **OpenRouter** (one account, one bill, many AI models).

**a. Get an OpenRouter key.** Go to <https://openrouter.ai>, create an account, add a
payment method, then open **Keys** and create a key (it starts `sk-or-v1-…`). Copy it —
it is shown once.

**b. Set the hard spending cap on OpenRouter — do this before anything else.** On the
OpenRouter site, go to **Settings → Limits** and set a **hard monthly credit limit** —
start at **$50**. This is the only limit the provider itself enforces. The app has its
own spending controls and they are good, but they run on this side of the connection;
the cap on OpenRouter's dashboard is the one that cannot be bypassed by a bug or by
someone editing a settings file. Set it now, not later.

**c. Put the key in the app.** In JLBC Search, go to menu → **Admin** → the **AI
Mode** section → **Key** → **Add a key**, paste it, then click **Save** in the bar at
the bottom. Every PC picks it up within a few seconds — no restart needed.

**d. Choose models.** Under **Standard** and **Deep Research**, pick a model from each
one's recommended list (already chosen for cost/quality) and Save. Standard is the
cheap everyday mode; Deep Research is the slower, pricier one.

**e. Set the in-app spending limits.** Admin → **AI Mode** → **Spending limits**, then
**Save**:

- **Each person, per month** — the default cap for everyone. **$10** is a sensible
  start. Blank = no limit, `0` = block everyone.
- **People with a different limit** — give someone their own number. Use the Windows
  username shown on *their* Settings page, spelled and capitalized exactly.
- **People with no limit at all** — e.g. the director; this beats any other limit.

**How the two caps fit together:** the in-app limits are per-person, per-calendar-month
and stop that person's AI Mode questions at their number (searching keeps working for
everyone). The OpenRouter account cap is the office-wide hard stop. Use both. Each
person can watch their own month-to-date on their Settings page; the admin sees
everyone under Admin → **Spending → Who spent what**.

> **Reminder for everyone:** public-record documents only. Anything uploaded to the
> shared folder can be retrieved by an AI Mode question and sent to the outside AI
> provider — so never upload confidential material.

---

## Where things are

| | |
|---|---|
| The app | `%LOCALAPPDATA%\JLBC-Search` |
| Budget documents, settings, usage records | the shared data folder you entered in step 1 |
| Log files (send these if something breaks) | `%LOCALAPPDATA%\JLBC-Search\logs` |

---

## If it will not start

1. Double-click the icon once more — the first click may have been while it was still
   starting.
2. If a message box names a log file, open the **`logs`** folder above, take the newest
   file, and send it to whoever supports this app. That file says what actually went
   wrong; a screenshot of the message box usually does not.
3. If the app opens but says it cannot find the budget documents, you are probably not
   connected to the network drive. Open File Explorer and browse to the shared folder
   once, then restart the app.

## If nobody can get into Admin

This is recoverable and you do not need to edit anything technical. In the **shared
data folder**, right-click → **New** → **Text Document**, and name it exactly:

```
RESET-ADMIN.txt
```

The next person to open the Settings page can claim admin. The file is used up when
someone claims, so it only works once.
