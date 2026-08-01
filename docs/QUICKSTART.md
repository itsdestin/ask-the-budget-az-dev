# JLBC Insight — Quick Start

One page. If you can unzip a file, you can install this. It needs no admin
rights and nothing already installed on your PC.

---

## 1. Install it (about 5 minutes)

1. Copy `JLBC-Insight-<version>.zip` **to your own computer first**. Do not
   extract it directly from the network folder — that is slow and it often
   stops partway through without saying so.
2. Right-click the copied zip → **Extract All…**
3. When it asks where to put it, paste this and press Enter:

   ```
   %LOCALAPPDATA%
   ```

4. Open the folder it created and double-click **`install.cmd`**.
5. It will ask for the **shared folder** — the network location holding the
   budget documents. Whoever set this up has the path; it looks something like
   `\\server\share\JLBC-Insight-Data`. If you do not have it yet, press Enter
   and set it later from inside the app.

You now have a **JLBC Insight** icon on your Desktop and in the Start Menu.

> **If Windows shows a blue "Windows protected your PC" box:** click **More
> info**, then **Run anyway**. That box appears for any program that has not
> been bought a code-signing certificate; it is not a virus warning.

---

## 2. Start it

Double-click the **JLBC Insight** icon. The first start takes 20–40 seconds
while it loads its search models; after that it is a few seconds.

You can now **search the budget documents and read fiscal notes**. That works
with no accounts, no keys, and no internet connection.

Closing the window does not shut the app down — clicking the icon again brings
it straight back.

---

## 3. Turn on AI Mode (admin only, about 10 minutes)

AI Mode is the part that answers questions in sentences instead of returning
documents. It is the only part that costs money, and only the admin sets it up.

**a. Claim the admin role.** Open the app, go to **Settings**. If nobody has
set up an admin yet, there is a banner offering it to you. Click it. This
happens once, for the whole office.

**b. Get an OpenRouter key.** Go to <https://openrouter.ai>, create an account,
add a payment method, then open **Keys** and create a key. Copy it — it is
shown once.

**c. Set the spending cap. Do this before anything else.**

On the OpenRouter site, go to **Settings → Limits** and set a **hard monthly
credit limit** — start at **$50**. This is the only limit the provider itself
enforces. The app has its own spending controls and they are good, but they run
on this side of the connection; the cap on OpenRouter's dashboard is the one
that cannot be bypassed by a bug in the app or by someone editing a settings
file. Set it now, not later.

**d. Paste the key into the app.** In JLBC Insight, go to **Admin → AI Mode
setup**, paste the key, and click **Test**. It will tell you plainly whether it
worked.

**e. Set a per-person monthly limit.** In **Admin → Spend limits**, set a
default — **$10 per person per month** is a sensible starting point. You can
raise individuals later, or set someone to 0 to block them entirely.

AI Mode is now on for everyone.

---

## Where things are

| | |
|---|---|
| The app | `%LOCALAPPDATA%\JLBC-Insight` |
| Budget documents, settings, usage records | the shared folder you entered in step 1 |
| Log files (send these if something breaks) | `%LOCALAPPDATA%\JLBC-Insight\logs` |
| The full handbook | **Help** inside the app, and a Word copy sitting next to the documents in the shared folder |

---

## If it will not start

1. Double-click the icon once more — the first click may have been while it was
   still starting.
2. If a message box names a log file, open the **`logs`** folder above, take the
   newest file, and send it to whoever supports this app. That file says what
   actually went wrong; a screenshot of the message box usually does not.
3. If the app opens but says it cannot find the budget documents, you are
   probably not connected to the network drive. Open File Explorer and browse to
   the shared folder once, then restart the app.

## If nobody can get into Admin

This is recoverable and you do not need to edit anything technical. In the
**shared folder**, right-click → **New** → **Text Document**, and name it
exactly:

```
RESET-ADMIN.txt
```

The next person to open the Admin page can claim it. Full explanation is in the
handbook under *If nobody can get into Admin*.
