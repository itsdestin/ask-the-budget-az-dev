import * as api from "../api";
import { extractorLabel, pct } from "./extractionDisplay";

// Documents that ARE in search right now and were read badly anyway.
//
// This is the gap the other two panels leave between them. `NeedsAttention`
// lists only documents the ladder REFUSED to write; `ExtractionChanges`
// lists only documents whose extraction method CHANGED. A document that is
// poor and saved satisfies neither — a DOCX has one extraction method so
// nothing can ever change, and a PDF where every method scored badly still
// has to keep one of them. Those are exactly the documents an admin most
// needs to know about, because they are the ones analysts are getting
// answers from.
//
// Renders NOTHING when empty — the same rule as the two panels above it,
// and the same reason: a box on screen every day teaches an admin to scroll
// past it. But note what the silence means and does NOT mean, because the
// two are easy to confuse: an empty panel says nothing ingested since this
// measure shipped scored badly. It does NOT say the corpus is clean. Every
// document ingested before it has no such measurement recorded and can
// never appear here, whatever state it is in. `scripts/structure_scan.py`
// is what audits those.
//
// Nothing here may say a document was verified, checked, validated, healthy
// or good — this measure detects ONE failure shape and certifies nothing. A
// passage scoring a perfect 0% has been observed carrying a units label
// wrong by a factor of 1,000.

export function PoorlyRead({ documents }: { documents: api.DegradedDocument[] }) {
  if (documents.length === 0) return null;

  return (
    <section
      className="card adm-panel adm-panel-alert"
      aria-labelledby="adm-poorly-read-h"
      data-testid="adm-poorly-read"
    >
      <div className="adm-panel-head">
        {/* Both facts, in the order they matter: it is being used, and it
            is bad. "Badly read" rather than "low quality" — the admin's
            model of this system is that it READS documents, and naming the
            step that went wrong is what makes the next sentence useful. */}
        <h2 id="adm-poorly-read-h">In search, but badly read</h2>
        <span className="adm-attention-count" data-testid="adm-poorly-read-count">
          {documents.length}
        </span>
      </div>

      {/* Said once for the panel, not per document: what an admin can
          actually DO. There is no button here on purpose — the ladder has
          already run every method it has, so a re-process gives the same
          answer, and the one action that helps (a better source file) is
          not something this screen can perform. Offering a button that
          changes nothing is worse than offering none. */}
      <p className="adm-attention-tried-label">
        The app kept the best reading it could get. Re-processing usually
        gives the same result; if a different copy of the file exists, it
        may read better. Until then, figures quoted from these documents
        may not say what they are counting.
      </p>

      <ul className="adm-attention-list">
        {documents.map((doc) => (
          <li
            key={doc.job_id}
            className="adm-attention-item"
            data-testid="adm-poorly-read-doc"
          >
            <p className="adm-attention-title">{doc.title}</p>
            <p className="adm-warn" data-testid="adm-poorly-read-share">
              {pct(doc.unlabelled)} of this document's passages are figures
              with no words — the number is readable, what it counts is not.
            </p>
            {/* Coverage sits beside it because the two DISAGREE, which is
                the entire reason this measure exists: the document that
                motivated it read 49% here and 31% bare. Showing only the
                flattering number is how the problem stayed invisible. */}
            <p className="adm-attention-tried-label">
              Read with {extractorLabel(doc.kept)}; {pct(doc.coverage)} of
              the page's text came out.
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
