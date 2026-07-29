// Honest stub: the Settings surface exists in the nav (and therefore needs a real
// route so the pill isn't a dead link), but nothing is configurable yet. No fake
// controls — deliberately just a statement of where it stands. Plan 5 replaces it.
// Styling reuses the mockup's `.card` panel; see the Settings block in app.css.
export function Settings() {
  return (
    <main className="stub-page" data-testid="settings">
      <div className="wrap">
        <section className="card stub">
          <h1>Settings</h1>
          <p>
            There are no settings yet. This surface is being built in Plan 5 — until then
            search and fiscal notes run on their defaults.
          </p>
        </section>
      </div>
    </main>
  );
}
