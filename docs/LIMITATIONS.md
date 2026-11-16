# Limitations

Draft for the Jamboree write-up. Update once the real runs are done.

**The cutoffs are drafts.** Every pass and caution threshold, every population rule and the HRD cutoff of 42 are starting values written by the engineering team. None has clinical sign-off yet. A verdict says whether a dataset can support a question under these draft rules; it is not a clinical finding.

**The field maps are unconfirmed.** Source column names for TCGA and SEER were written from published variable metadata before any file was downloaded. Until they are checked against the real files, a variable can show as "not loaded" only because its name is wrong in the map.

**What open-tier TCGA cannot show.** Germline calls are controlled access, so question 5 is scored as HRD from tumor data. TCGA has no commercial recurrence score, no distant recurrence endpoint (progression-free interval stands in), and grade is missing in the data the adapter pulls. Tumor size in millimetres and family history have no identified source column. TCGA patients were selected for tissue availability and are not a population sample.

**SEER treatment limits.** SEER releases chemotherapy and radiation as "yes" or "no/unknown", so untreated and unrecorded patients cannot be separated. It carries no endocrine therapy, menopausal status, drug names, ovarian suppression, recurrence, or germline or HRD data. Systemic therapy before surgery is read from a sequence field that does not record intent. The Oncotype DX score needs a separate specialized database.

**SEER and TCGA are never linked.** Each is scored on its own. SEER is also used as a population reference by comparing group shares, using only the population rules SEER can apply.

**Ovarian suppression is recorded only as "yes".** It is read from drug names, so its completeness is the share recorded as treated, not the share with a known answer.

**Small-cell protection is partial.** SEER reports suppress counts below the threshold but do not do complementary suppression. A person has to read a SEER report before it is shared.

**What was not tested.** The new code is tested on invented rows only. No real TCGA supplement file or SEER export has been run through it. The optional GDC API fields (drug names, treatment dates and intent, HER2 test method) have not been checked against the live API and are off by default. The four placeholder checks (site effects, confounding, leakage, standards conformance) are not built and are left out of the five question tasks. The data card layout with the new panels has not been reviewed in a browser.
