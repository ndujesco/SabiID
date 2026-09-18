# SabiID demo, voiceover script

Eight sections, one per section of the silent recording (`demo/out/demo.mp4`). A
green banner at the bottom of the frame tells you which section is playing, and
`demo/out/sections.json` has the exact start and end time of each one.

**How to use this**

1. Record one voice note per section. Name them `demo/narration/VN01.m4a`
   through `VN08.m4a` (mp3, wav, aac and opus also work). Speak it in your own
   words. The text below is a guide, not a teleprompter.
2. Aim near the target length shown for each section. A few seconds over or under
   is fine. The assembler holds on the last frame or trims to match your audio.
3. Run `python3 docs/build_srt.py`. It reads your voice notes, builds
   `demo/out/demo.srt`, and writes `demo/out/assemble.sh`.
4. Run `bash demo/out/assemble.sh`. It produces `demo/out/demo_final.mp4` with
   your narration and burnt-in subtitles.

The `>>>` line in each section is the one sentence to land clearly.

<!--SECTION 1 | The problem: one question, the whole ID card | target 26s-->
Every day, somebody gets asked to prove one small thing. A shop wants to know if
you are over 18. A bank wants to know that the name on the form belongs to a
verified person. The question is a yes or a no. What you hand over is your whole
ID, and it gets photographed, saved, and forwarded, and every copy is somewhere
your details can leak from later. SabiID is a broker. It sits between the
identity sources and the people checking identity, and it passes back the answer
alone.
>>> One question should cost one answer, not your whole record.
<!--/SECTION-->

<!--SECTION 2 | Enrolled once, values stay on the phone | target 29s-->
This is the citizen's own phone. Adaeze enrolled once with her NIN and her BVN.
What she got back is a credential signed by the gateway, and its body holds only
salted hashes of her claims, not the claims themselves. Her name, her date of
birth, her state, they live here on the device and nowhere else. She can reveal a
value to herself, like her date of birth. Nobody else sees any of it unless she
chooses to send it.
>>> The record stays with the person. The gateway keeps a signature, not a copy.
<!--/SECTION-->

<!--SECTION 3 | A bank asks a narrow question | target 25s-->
Now a bank wants to open an account for her. Instead of asking for the ID, it
asks three narrow things. Is this a verified identity. Is she over 18. Does the
name on our form match. It never asks for the date of birth, and it never asks
for the address. It sends that short list to Adaeze and waits for her to approve
it on her phone.
>>> The bank asks for the least it can get away with, not the most.
<!--/SECTION-->

<!--SECTION 4 | The consent moment, field by field | target 29s-->
Here is the request on Adaeze's phone. She sees every field the bank wants. She
approves being a verified identity, and she approves being over 18. She unticks
the name check, because she does not want to confirm the exact spelling this
time. She confirms it is her with a code from her SIM. Whatever she did not tick
is simply withheld. Consent here is field by field, and she holds the switch.
>>> Nothing is shared until she taps approve, and only what she taps.
<!--/SECTION-->

<!--SECTION 5 | What the bank gets back | target 34s-->
This is everything the bank receives. Yes, it is a verified identity. Yes, she is
over 18. The name check is withheld, because she chose not to answer it. There is
no date of birth anywhere in this response. The answer carries a signature from
the gateway, and the bank checks that signature right here in the browser against
the gateway's public key. It needs nothing from us. Then a hospital asks for a
genotype, which nobody has verified. The gateway does not guess. It says so, and
points to where it can be done.
>>> A signed yes or no, verifiable on the partner's own machine, and honest about
what it does not know.
<!--/SECTION-->

<!--SECTION 6 | The proof-of-check log, and catching an edit | target 28s-->
Every question through the gateway is one line here, and each line carries the
hash of the line before it. A line holds a pseudonymous ID, the partner, the
fields asked, and the outcomes. It never holds a date of birth, an address, or a
biometric. We press verify and every line checks out. Now we quietly edit one
past line. Verify points straight at it and says it was changed after it was
written. We put it back, and the chain is whole again.
>>> The log proves a check happened, and it cannot be rewritten later without the
edit showing.
<!--/SECTION-->

<!--SECTION 7 | Ghost workers and ghost pensioners | target 35s-->
This is the same mechanism, asked every month. Before this ministry pays, SabiID
asks each line one thing. Is this still the same living person we enrolled. The
staff who answer with a fresh face check are paid. Five lines are held. One has
no NIN record and was never a person. One is listed as deceased at the Civil
Registration service. One has relocated and stopped answering. One offered a
sample that did not match. And one is a real staff member who was just out of
network signal. The system cannot tell that last one from a ghost, so it sends
them to a human. On this run it pays about 1.4 million naira and holds back
955,000.
>>> The audit line becomes the reason a payment was stopped, and a real person
still gets a human's second look.
<!--/SECTION-->

<!--SECTION 8 | When the lights go out, and the no-smartphone path | target 40s-->
Power cuts and dropped networks are normal here, so we built for them. We run the
payroll with the identity sources offline. Nothing pays. Every line is queued.
When the link comes back, one reconcile step replays the queue, and the log
records the outage and the recovery as their own lines. The chain still verifies
across the gap. And for the citizen with a basic phone and weak signal, the same
approvals work over a USSD short code. They dial in, see the check waiting,
approve it, and view their last few checks. The face step is skipped on a feature
phone, and the person is told it was skipped.
>>> It keeps working when the lights go off, and it does not shut out the person
without a smartphone.
<!--/SECTION-->
