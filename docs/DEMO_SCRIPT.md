# Demo video shooting script — eight scenes, 165 seconds

This is the shooting script for the Devpost demo video. The video follows two shipments, A and B, that carry the same booking data and end in different decisions because of one document: the purchase invoice. It runs 165 seconds (2:45), under the three minutes the rules allow, and is uploaded to YouTube as a public video.

The narration under each clip is the text in `SCENES` in `scripts/build_narration.py`. If you change one, change the other, then run `python scripts/check_demo_script_sync.py`.

## What the cut must satisfy

- Less than three minutes. The rules say judges need not watch beyond three. This cut is 165 seconds.
- Footage of the real product working. A side-by-side of A and B is an edited placement of two recorded screens and is captioned as such; nothing is composed to look like a product screen, button or input field that does not exist.
- No third-party trademarks and no copyrighted music. Music is off by default.
- NVIDIA Nemotron and Nebius Token Factory are said aloud (clips 2 and 6) and shown as captions.
- The documents are synthetic. The first document on screen carries the caption "Synthetic demo documents"; they are never presented as real certificates or customer files.
- No API key, password or upload token is ever visible in frame or in the exported file.

## Length table

| Clip | Scene | Length | Screen |
|---|---|---|---|
| 1 | Two identical shipments | 12s | A and B side by side (edited) |
| 2 | Nemotron screens both | 26s | Case A's trace: Nano hops, Tavily sources, HS check, then the finding and required documents |
| 3 | Evidence requested and received | 20s | Request info, three links, a signed-out upload, the receipt record |
| 4 | The invoice splits the cases | 28s | Invoice line, extraction, Re-evaluate, Evidence check for A then B |
| 5 | A person decides, then it executes | 24s | Reason, Release and Confirm for A; reason, Block and Confirm for B |
| 6 | Nemotron in the trace | 22s | Per-hop model, tokens and cost; an Ultra auto-debate and its Super investigation |
| 7 | The next reviewer can follow | 18s | The case timeline, "What happened" |
| 8 | Close | 15s | A and B final states side by side, then the end card |
| | | **165s** | |

Timeline: 1: 12s   2: 26s   3: 20s   4: 28s   5: 24s   6: 22s   7: 18s   8: 15s     total 165s

## Part 0 — before you press record

1. **Build.** The deployed build is the one named in the submission text. Write down the Cloud Run revision from `/health` and the commit it was built from; both go into the production record.
2. **Two new cases.** Create two NEW case ids, A and B, with identical booking data: Vietnam to United States, plywood, HS 4412.33, 22,000 kg, declared value 28,000 USD. Do not clear the board and do not reuse a case an earlier visitor decided.
3. **Six synthetic PDFs, one page each.** For each case: a certificate of origin (country of origin Vietnam), a producer declaration (input origin Vietnam), and a purchase invoice. A's invoice is from VN Timber JSC with country of origin of goods Vietnam; B's invoice is from Linyi Veneer Co., Ltd. with country of origin of goods China. The generator is `scripts/rev2_e2e/gen.mjs`; check that the only difference between A and B is the invoice.
4. **Upload links.** The request-evidence screen shows full URLs. `scripts/rev2_e2e/run.mjs` parses relative paths, so copy the three full URLs by hand, or fix the parsing first. Never leave a token in a frame.
5. **A dry run before the real take.** Run both cases from request to decision once and read the result: A should end `RELEASED_BY_HUMAN` and B `BLOCKED_BY_HUMAN`, A's re-evaluation should read provided and B's contradicted. Use the take only if the extracted invoice country matches the PDF text. Open A's trace and write down which hops ran and on which model: Nano fraud and compliance, the HS classifier, and whether `auto_debate` (Ultra) fired. The plywood finding floors the case at 45, so the debate fires only if Nano scored it 30 or lower. Clip 6 depends on this.
6. **Capture.** Record at 2560×1440 or larger and check the export at 1920×1080 (16:9). Record important cards and document lines as separate close-ups; never shrink a whole screen to make small text readable. Pause the mouse before each click; no idle sweeps, no sudden scrolls.
7. **Waiting.** Cut waiting time and caption the cut "Time condensed". Keep the original waiting time in the production record.
8. **Colours of the edited layer.** Case A green #246B4E on #F8FBF9; case B wine #8A3F5C on #FBF8F9; explanations blue #244E95 on #F8F9FB. Always add a word as well as a colour ("Provided", "Contradicted"). Keep the product's own dark interface as recorded.
9. **Captions.** English, 40–44 px at 1080p, two lines at most.

## Clip 1 — Two identical shipments (0:00 → 0:12, 12s)

> Two shipments look identical at booking. Both declare Vietnamese plywood. Would you release both? The input origins are still unverified.

**Screen.** The real screens of A and B placed side by side in the edit. Vietnam → United States and HS 4412.33 sit in the same position on both. The name Floorline is visible from the first frame, and the two different case ids stay visible.

**Caption.** Same booking information. Missing input-origin evidence.

## Clip 2 — Nemotron screens both (0:12 → 0:38, 26s)

> Floorline screens both cases for a freight forwarder, on Nebius Token Factory. NVIDIA Nemotron 3 Nano scores fraud and compliance with live Tavily searches, and checks the tariff code against the goods. The rules set a risk floor the model may raise, never lower, and on this lane they ask where the plywood inputs came from.

**Screen.** Case A's trace, the real one from the take. First the fraud and compliance hops with their model `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and Nano's score; then the compliance hop's Tavily sources (titles and links) for the shipper and receiver; then the HS classifier hop agreeing that 4412.33 is plywood. End on the case page: the risk floor of 45 above Nano's score, the finding ORIGIN_INPUTS_UNVERIFIED and the list of required documents. Show the words "Freight forwarders" once. B's trace is not filmed; one caption says B ran the same hops.

**Caption.** Nemotron 3 Nano scores · the rules set the floor · the model can raise it, never lower it

**Check.** If a Tavily search on A is marked cached (a name searched in the last hour), the caption says "cached", not "live". Nano's low score is the point of the clip: the model alone would let A through, and the floor is why it waits.

## Clip 3 — Evidence requested and received (0:38 → 0:58, 20s)

> The reviewer requests a certificate of origin, a producer declaration, and input purchase invoices. The shipper uploads each document through its own link, without an account. Floorline records the documents and extracts their contents with MiniCPM-V.

**Screen.** Request info, then Confirm, then film the three links. Switch to a signed-out browser and show one upload as the example. After the rest are submitted, return to the reviewer's side and show the receipt record. The wait for processing is cut and captioned "Time condensed".

**Caption.** Request evidence → Submit documents → Verify contents

**Check.** The upload page does not necessarily show the document type or the documents still missing. The explanation of what is required is an editing caption and is never presented as part of the real interface. Each document type has its own link.

## Clip 4 — The invoice splits the cases (0:58 → 1:26, 28s)

> The first two documents match. The purchase invoices reveal the difference. Case A identifies Vietnamese inputs. Case B identifies Chinese veneer, contradicting the declaration. Floorline marks A as provided and B as contradicted. Both results stay linked to the submitted evidence.

**Screen.** The relevant line of A's invoice, then B's, with only "Country of origin of goods" highlighted: Vietnam, then China, in the same position. Run Re-evaluate for real. Cut to the Evidence check result and the concrete contradiction. Hold the A and B comparison still for the last 4 seconds.

**Caption.** A Consistent evidence   B Conflicting evidence

**Values to leave on screen.**

| | A | B |
|---|---|---|
| Invoice origin | Vietnam | China |
| Evidence check | provided | contradicted |
| Decision | Release | Block |
| After execution | RELEASED_BY_HUMAN | BLOCKED_BY_HUMAN |

**Check.** "Provided" means the papers are consistent; it is not a guarantee that they are genuine or lawful. A's risk floor is not lowered by the documents; a person confirms and releases. B is not declared fraud; the contradiction is why the reviewer chooses to stop it.

## Clip 5 — A person decides, then it executes (1:26 → 1:50, 24s)

> The reviewer reads the evidence and authorizes release for A, then blocks B with a reason. Confirmation comes before execution. The system records the person, evidence version, and the decision sent. These are human decisions, supported by AI and checks.

**Screen.** A: enter the reason, Release, Confirm. B: enter the reason, Block, Confirm. The current console runs approve and execute one after the other after a single Confirm, so do not invent a two-step button. Leave each final state on screen long enough to read.

**Caption.** A Released by reviewer   B Blocked by reviewer

**Reasons to type.** A: "Papers agree Vietnam origin throughout". B: "Invoice shows China origin veneer". Adjust them at the take to what the real document and the extraction show.

**Check.** This clip and clips 4 and 7 are the heart of the video: the invoice difference is readable, the re-evaluation difference is readable, and it is clear that a person decided, confirmed, and then the decision was executed. Follow the same case from source document to final state without reordering.

## Clip 6 — Nemotron in the trace (1:50 → 2:12, 22s)

> Every hop in the trace names its model, tokens and cost. When the floor sits fifteen points above Nano's score, Nemotron 3 Ultra debates the case and calls Tavily itself. It can send a case to Nemotron 3 Super for investigation, never clear it.

**Screen.** 0–6s: A's trace with each hop's model, tokens and cost readable, and the case total. 6–22s: the `auto_debate` hop on `nvidia/Nemotron-3-Ultra-550b-a55b`: the Tavily query Ultra chose, its CONFIRM or DISAGREE with the confidence, and the `investigation` hop on `nvidia/nemotron-3-super-120b-a12b` when it ran. Use A if the debate fired on A (Part 0, step 5). If it did not, film a case on the board whose trace has both hops (on 21 Oct `CASE-VFL-2026-91177` did) and caption it "Another case on the board"; never present that trace as A's.

**Check.** Do not move to a full-screen list of the seven agents or to code. If Ultra's search is marked cached, say so.

**Caption.** Nano screens · Ultra argues the dispute · Super investigates

## Clip 7 — The next reviewer can follow (2:12 → 2:30, 18s)

> The timeline ties each decision to the reviewer and evidence version, then records dispatch. A second reviewer can inspect the same chain, from missing information to the action taken.

**Screen.** On the case page, "What happened": Requested, Received, Re-evaluated, the approver, the evidence version, Executed, in that order. Scroll at one steady speed in one direction. Finish with the evidence and the execution record in the same view.

**Caption.** Evidence version  /  Reviewer  /  Decision dispatched

**Check.** The message id is the record of the send to Pub/Sub. It is never shown as proof that a third-party ERP or warehouse system finished processing.

## Clip 8 — Close (2:30 → 2:45, 15s)

> Floorline helps freight forwarders turn missing information into a documented decision: move a case forward when evidence supports it, and stop it when the evidence conflicts.

**Screen.** The final screens of A and B re-placed side by side, each with a one-line reason. In the last 3 seconds: Floorline, the public demo address and the GitHub address, and the author's name (Hoa Chau Phuoc). No other company name, logo or credit appears.

**Caption.** From missing evidence to a documented decision.

## Assembling

1. Edit the comparison cuts first (clips 1, 4 and 8), then fit the audio and the captions to the eight scenes.
2. Drop the eight clips in order 1..8, butted together, no transitions. The scene lengths are 12s, 18s, 22s, 30s, 26s, 22s, 20s and 15s, in scene order, so the cut points land at 0:12, 0:30, 0:52, 1:22, 1:48, 2:10 and 2:30.
3. Play the export alone, with sound and with captions, before upload. Check it against the README and the submission text: the models named in the voice are the models the product ran, and every number on screen is from the recorded take.
4. Upload to YouTube as Public, and paste the link into the Devpost form.

## Regenerating the narration

The audio is generated, not spoken live. `scripts/build_narration.py` synthesises `build/narration.wav` and `build/narration.srt` from `SCENES`, per sentence, with Google Cloud Text-to-Speech. It is billable and needs `texttospeech.googleapis.com` enabled and application-default credentials, so a person runs it.

```bash
python scripts/check_narration_budget.py     # offline: does each scene fit its clip?
python scripts/check_demo_script_sync.py     # offline: does this file quote SCENES?
python scripts/build_narration.py            # billable
```

Run the two offline checks first: the fit check inside `build_narration.py` runs after the paid call and only warns. After generating, measure each scene against its clip and shorten the writing, not the reading, if a scene runs over. Do not lay new video over old audio.

## Do not say

- That the documents are real certificates or customer files.
- That "provided" proves a document is genuine or lawful.
- That the AI released or blocked a shipment. A person decides; the AI and the checks support.
- That the floor was lowered for A.
- "Live" for a Tavily result the trace marks as cached.
- A reduction rate, a detection accuracy on real customers, or the completion of work in an external warehouse system. None of these is demonstrated in the video.
