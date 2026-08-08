# Hook Engineering Playbook — Atmosfera Viral

Operational reference for the script generator: a scoring rubric, a hook taxonomy, 18 gold-standard reference pautas, a list of retention/policy anti-patterns, and a repeatable method for turning one theme into several strong, distinct hooks. Built for this channel specifically — dark-cinematic, second-person, one line at a time, silence between lines, no CTA. Sources are listed in the appendix only, so they don't pollute the material a smaller model will imitate.

---

## 1. Hook Principles & Scoring Rubric

Each dimension below maps to a documented mechanism of attention, curiosity, or memory — not a stylistic trend, which is why this rubric should stay stable even as platform formats shift. Score a candidate hook 0–10 on each dimension. A usable hook averages roughly 7+ with no single dimension below 5.

**1. Specificity** — Names one exact behavior, object, or moment instead of a general trait or theme.
- 3/10: "You avoid things." (fits anyone, any time)
- 8/10: "You've reread the same message three times before replying." (one behavior, one moment)

**2. Self-Contradiction** — Negates a label the viewer already applies to themselves and replaces it with a sharper, less comfortable one.
- 3/10: Confirms what's already believed ("Discipline is hard.")
- 8/10: Reverses a specific self-diagnosis ("It's not laziness, it's fear of being watched.")

**3. Gap Size** — The distance between what the viewer already half-senses and what the line names. A small, ego-relevant gap reads as recognition; a large, distant one reads as trivia and pulls less curiosity, not more.
- 3/10: A gap so wide it feels like someone else's problem.
- 8/10: A gap so narrow it feels like the viewer's own half-formed thought, finished for them.

**4. Concreteness** — Built from images and physical nouns/verbs rather than abstractions.
- 3/10: "Growth requires discomfort."
- 8/10: "Same door. Still closed."

**5. Pattern Break** — The line's shape or claim deviates from what the niche normally says, so it registers as new rather than blending into familiar wallpaper.
- 3/10: Interchangeable with any mindset caption ("You are stronger than you think.")
- 8/10: A framing the viewer hasn't heard put this way before.

**6. Open Loop** — The line is deliberately incomplete: it states a tension the rest of the script must resolve, not a finished thought.
- 3/10: A complete observation that needs nothing after it.
- 8/10: A claim that only fully makes sense once the last line lands.

**7. Angle Originality (Swap Test)** — Tied to one specific, named mechanism; could only this reframe have produced this exact line?
- 3/10: Any account in the niche could post it unchanged.
- 8/10: No other pauta in this set shares its underlying mechanism.

**8. Economy** — Every word is load-bearing.
- 3/10: Contains a warm-up clause before the actual point starts.
- 8/10: Removing any single word would break the line.

---

## 2. Hook Taxonomy

Ten archetypes cover this niche without repeating a mechanism. Combine two in one hook only rarely — most of the power comes from running each mechanism clean.

**Assumption Reversal** — *Mechanism:* takes a label the viewer already applies to themselves and swaps it for a more specific, less comfortable one; maximum self-contradiction at minimum gap size. *Template:* "It's not [comfortable label], it's [specific truth]." *Example:* "It's not laziness, it's fear of being watched."

**Mislabel Correction** — *Mechanism:* renames a feeling (not a trait) by attaching a cause the viewer hadn't considered. *Template:* "You're not [surface feeling], you're [underlying cause]." *Example:* "You're not relaxing, you're avoiding a feeling."

**Second-Person Indictment** — *Mechanism:* states an exact, observable behavior in flat declarative voice with no judgment words attached; the neutrality is what makes it land as being seen. *Template:* "[Specific behavior] is just a socially acceptable way to [real function]." *Example:* "Busy is just a socially acceptable way to avoid yourself."

**Silent Confession** — *Mechanism:* names a private thought the viewer has had but never said aloud; collapses distance instantly because a stranger naming an unspoken thought reads as unusually perceptive. *Template:* "You've [private thought/fantasy], more than once." *Example:* "You've imagined leaving everything you built, more than once."

**False Cause Reveal** — *Mechanism:* names the culprit the viewer already blames, then swaps it for the real mechanism — a reversal that partly resolves inside the hook while still opening a "how" loop. *Template:* "It was never [assumed cause], it was [real cause]." *Example:* "It was never time, it was a decision you avoided."

**Delayed Consequence** — *Mechanism:* connects a small, currently invisible habit to a compounding cost, using scale against scale instead of drama. *Template:* "Every [small habit] [compounding cost]." *Example:* "Every small thing you avoid shrinks you a little."

**Comfort Exposure** — *Mechanism:* reclassifies something treated as safe as the actual source of harm — a category error correction, since safety and danger are normally treated as opposites. *Template:* "[Comfort object] isn't safety, it's [danger]." *Example:* "Comfort isn't safety, it's a slower kind of losing."

**Identity Fork** — *Mechanism:* splits the viewer into two competing present-tense versions of themselves, forcing an immediate self-sort instead of a future hypothetical. *Template:* "There's a version of you that [acts]. [Other version] [doesn't]." *Example:* "There's a version of you that doesn't wait for Monday."

**Time Compression** — *Mechanism:* collapses a long future timeline into the immediate present, making an abstract "someday" consequence feel like it's being decided right now. *Template:* "In [future timeframe], [this moment] is the reason or the excuse." *Example:* "In five years, tonight is the reason or the excuse."

**Silence as Diagnosis** — *Mechanism:* reinterprets an absence — a thing not done — as meaningful rather than neutral, which unsettles because absence usually feels like nothing happened. *Template:* "[Absence/inaction] says something about you, not [external excuse]." *Example:* "The message you never answered says something about you."

---

## 3. Reference Pautas (18 Complete Examples)

Each roteiro below targets roughly 36–48 spoken words across 8 lines. That assumes a deliberate, dramatic narration pace (~110–140 wpm — slower than a typical energetic Shorts read) plus the silence beats between lines the format calls for. The fixed constraints are the line count (8) and the 22–26s total; word count is the variable to flex if the actual TTS voice or render pacing runs faster or slower than that assumption. The line count doubled from 5 to 8 in the round that raised the target duration — total video length is exactly the narration length, so more beats is the only lever that lengthens the video, and each added beat stays one short line, never a longer one. Each pauta below runs a different taxonomy mechanism and a different underlying theme — none should read as a reordering of another.

```json
{
  "pautas": [
    {
      "tema": "Procrastination as fear of being watched, not laziness",
      "hook": "It's not laziness, it's fear of being watched",
      "roteiro": "It's not laziness, it's fear of being watched\nSo you wait for no one to see\nThe moment never comes\nYou call it timing\nIt was always the fear\nWaiting becomes who you are\nAnother day folds shut\nSame door. Still closed.",
      "titulo": "The Real Reason You Keep Waiting",
      "descricao": "Not motivation. Not laziness.\nSomething quieter, and harder to admit."
    },
    {
      "tema": "Small avoidances compound into a smaller self",
      "hook": "Every small thing you avoid shrinks you a little",
      "roteiro": "Every small thing you avoid shrinks you a little\nNot all at once\nA missed call. A closed tab.\nAn email left unread\nNone of it looks like damage\nYou barely notice the trade\nThen you catch your reflection\nUntil the outline changes",
      "titulo": "The Cost of the Small Things You Skip",
      "descricao": "It never looks like damage.\nIt just adds up quietly."
    },
    {
      "tema": "Scrolling as anesthesia for an unnamed feeling",
      "hook": "You're not relaxing, you're avoiding a feeling",
      "roteiro": "You're not relaxing, you're avoiding a feeling\nThe phone isn't rest\nIt's a place to not be\nThe feeling doesn't leave\nIt waits outside the screen\nYou scroll to keep it there\nThen the light goes dark\nThere when the battery dies",
      "titulo": "What Scrolling Is Actually For",
      "descricao": "The phone was never about the phone.\nIt was about not sitting still."
    },
    {
      "tema": "Comfort zone as slow decay, not safety",
      "hook": "Comfort isn't safety, it's a slower kind of losing",
      "roteiro": "Comfort isn't safety, it's a slower kind of losing\nNothing hurts\nNothing changes\nYou call it stability\nThe walls stay exactly where they are\nIt's decay with better lighting\nNo alarm ever rings\nQuiet, the whole way down",
      "titulo": "The Danger No One Warns You About",
      "descricao": "It doesn't feel like danger.\nThat's what makes it dangerous."
    },
    {
      "tema": "Burnout relabeled as meaninglessness, not overwork",
      "hook": "It's not burnout, it's doing something that means nothing",
      "roteiro": "It's not burnout, it's doing something that means nothing\nThe hours aren't the problem\nSleep doesn't fix it\nThe reason is missing\nYou keep looking for rest\nRest was never the gap\nYou call it tired\nThe alarm rings. Nothing answers.",
      "titulo": "The Exhaustion That Isn't About Hours",
      "descricao": "The hours were never the problem.\nThe meaning was missing, not the energy."
    },
    {
      "tema": "Silent confession: the fantasy of walking away from everything built",
      "hook": "You've imagined leaving everything you built, more than once",
      "roteiro": "You've imagined leaving everything you built, more than once\nNot because you hate it\nSome days it's just a costume\nYou picture the door\nThen you put the costume back on\nYou never say it out loud\nSaying it would make it real\nSo it waits",
      "titulo": "The Thought You Don't Say Out Loud",
      "descricao": "Everyone who's built something has had it.\nAlmost no one admits it."
    },
    {
      "tema": "Time compression: tonight becomes the reason for future regret",
      "hook": "In five years, tonight is the reason or the excuse",
      "roteiro": "In five years, tonight is the reason or the excuse\nNot the year\nJust tonight\nThe same small choice\nMade again in the dark\nOne decision, repeated\nIt never feels like the one that counts\nLater, it's just tonight",
      "titulo": "What Tonight Will Turn Into",
      "descricao": "Small nights don't feel like much.\nThey're the only thing that adds up."
    },
    {
      "tema": "Identity fork: the one who starts now vs. the one waiting for Monday",
      "hook": "There's a version of you that doesn't wait for Monday",
      "roteiro": "There's a version of you that doesn't wait for Monday\nIt starts tonight, unprepared\nThe other keeps preparing\nBuys the planner. Reads the guide.\nPreparing is hiding\nMonday keeps not coming\nOne of them acts\nOnly one is real yet",
      "titulo": "The Version of You Still Waiting",
      "descricao": "One starts messy.\nThe other just starts later, forever."
    },
    {
      "tema": "False cause: not lack of time, an undecided decision",
      "hook": "It was never time, it was a decision you avoided",
      "roteiro": "It was never time, it was a decision you avoided\nYou had the hours\nYou filled them with almost\nYou hadn't decided\nDeciding meant it could fail\nSo you left it open\nOpen felt safer than wrong\nNot deciding was riskier",
      "titulo": "The Real Reason It's Still Not Done",
      "descricao": "Time was never the missing piece.\nThe decision was."
    },
    {
      "tema": "Silence as diagnosis: the unanswered message you sent",
      "hook": "The message you never answered says something about you",
      "roteiro": "The message you never answered says something about you\nNot about them\nYou read it twice\nYou knew what it opens\nSo you let it sit\nA day. Then a week.\nSilence became the reply\nYou're avoiding it now",
      "titulo": "What Your Unanswered Messages Mean",
      "descricao": "It's rarely about being busy.\nIt's about what a reply would open."
    },
    {
      "tema": "Perfectionism as a way to delay finding your actual limit",
      "hook": "Perfectionism isn't high standards, it's staying unfinished",
      "roteiro": "Perfectionism isn't high standards, it's staying unfinished\nUnfinished can't be judged\nUnfinished can't fail\nSo you keep polishing\nOne more pass. One more week.\nDone would mean a verdict\nYou'd rather not know\nSafety, wearing quality's mask",
      "titulo": "What Perfectionism Is Actually Doing",
      "descricao": "It's not about the details.\nIt's about never finding out."
    },
    {
      "tema": "Busyness as avoidance of one honest conversation with yourself",
      "hook": "Busy is just a socially acceptable way to avoid yourself",
      "roteiro": "Busy is just a socially acceptable way to avoid yourself\nNo one questions it\nIt looks like ambition\nYou fill every hour on purpose\nSo there's no gap to sit in\nIt's a hiding place\nThen the week finally ends\nEmpty calendar. Still there.",
      "titulo": "What Busy Is Actually Hiding",
      "descricao": "Nobody interrupts someone who looks productive.\nThat's exactly why it works."
    },
    {
      "tema": "The compounding cost of one habitual glance at someone else's life",
      "hook": "One glance at someone else's life costs more than you think",
      "roteiro": "One glance at someone else's life costs more than you think\nNot just once\nIt's the tenth today\nEach one taxes you\nA little less yours after\nYou didn't sign up for it\nStill you keep score\nBehind in a race no one announced",
      "titulo": "The Hidden Cost of Comparing Yourself",
      "descricao": "It's not the big moments that drain you.\nIt's the small, repeated ones."
    },
    {
      "tema": "Needing approval as a cage built one small yes at a time",
      "hook": "Every yes you didn't mean built the cage you're in",
      "roteiro": "Every yes you didn't mean built the cage you're in\nOne at a time\nSmall enough to ignore\nEach one bought a little peace\nEach one cost a little room\nNow the walls have shape\nYou built it to be liked\nIt looks like you",
      "titulo": "How the Cage Gets Built",
      "descricao": "Nobody builds it all at once.\nIt's assembled from small agreements."
    },
    {
      "tema": "Lack of motivation relabeled: the decision is made, follow-through is stalling",
      "hook": "You already decided, you're just stalling the follow-through",
      "roteiro": "You already decided, you're just stalling the follow-through\nThe decision happened days ago\nYou keep re-deciding it\nWhat's left isn't choice\nIt's just friction\nYou dress it up as thinking\nThinking ended already\nFriction isn't doubt",
      "titulo": "The Decision You've Already Made",
      "descricao": "Motivation isn't what's missing.\nThe decision already happened."
    },
    {
      "tema": "Time compression: years spent waiting for a start date that never comes",
      "hook": "You've been waiting for a start date that isn't coming",
      "roteiro": "You've been waiting for a start date that isn't coming\nMonday passed a hundred times\nJanuary passed too\nEach one looked almost right\nNone of them were the sign\nNo perfect one was coming\nThe waiting was the plan\nOnly this one, happening now",
      "titulo": "The Start Date You're Still Waiting On",
      "descricao": "It was never going to announce itself.\nIt just had to be chosen."
    },
    {
      "tema": "Silent confession: resentment toward people who look like they have it together",
      "hook": "You've resented people who look like they have it together",
      "roteiro": "You've resented people who look like they have it together\nNot because they're better\nBecause they look decided\nThey seem to know the ending\nYou're still editing the start\nYou feel like a draft\nUnsure it will ever ship\nA draft envies the finished",
      "titulo": "What That Resentment Is Really About",
      "descricao": "It's rarely about them.\nIt's about feeling unfinished next to them."
    },
    {
      "tema": "Constant background noise as avoidance of one specific silence",
      "hook": "The noise isn't entertainment, it's a wall around one silence",
      "roteiro": "The noise isn't entertainment, it's a wall around one silence\nMusic, notifications, something on\nNever nothing\nNot about enjoying it\nAbout not being alone with it\nKeeping one silence away\nYou almost hear it in the gaps\nThe silence that would ask something",
      "titulo": "The Real Job of All That Noise",
      "descricao": "It's not about missing out.\nIt's about not being asked something."
    }
  ]
}
```

---

## 4. Anti-Patterns

Each pattern below either breaks the channel's own format rules, measurably hurts distribution on-platform, or both — see the appendix for sourcing.

**1. Rhetorical question opener**
- Before: "Ever feel like you're not good enough?"
- After: "You rehearse conversations that already ended."
- Why: a question invites a mental "no" that closes the loop instead of opening it — and the format bans it outright.

**2. Vague abstraction opener**
- Before: "Discipline matters."
- After: "It's not laziness, it's fear of being watched."
- Why: fails specificity and concreteness at once; nobody disagrees, so nothing opens.

**3. Result promise**
- Before: "Do this for 30 days and your life changes."
- After: cut the promise; end on the unresolved image instead.
- Why: matches platform "malicious clickbait" definitions almost exactly — a claim the video itself can't verify — and is banned in the format regardless.

**4. CTA inside an 8–12s video**
- Before: "Follow for more." / "Watch till the end."
- After: cut it; the last line is the last sound.
- Why: engagement-bait detection actively suppresses reach for exactly this pattern — it is a distribution penalty, not just an aesthetic one.

**5. Generic empowerment cliché**
- Before: "You are stronger than you think."
- After: "You didn't call. That was the choice."
- Why: fails the swap test; could caption any mindset post ever made.

**6. Summarizing final line**
- Before: "So remember: discomfort is growth."
- After: "Same door. Still closed."
- Why: a summary re-closes analytically what the hook opened emotionally — it reads as a lecture, not a recognition.

**7. Intensity via punctuation**
- Before: "STOP MAKING EXCUSES!!"
- After: flat declarative delivery; let the image carry the weight.
- Why: breaks the format rules directly, and fails Pattern Break — caps and exclamation points are the niche's own cliché.

**8. Hook that outruns the render limit**
- Before: a 95-character hook gets clipped mid-word by the renderer's ellipsis.
- After: cut modifiers first ("really," "actually," "honestly"), then re-test under 60.
- Why: mechanical, not stylistic — anything past ~88 characters is truncated before the twist is ever read.

**9. Real-world citation**
- Before: "Even [a well-known athlete] almost quit."
- After: anonymize completely; the discomfort has to belong to the viewer, not a public figure.
- Why: a named person or brand shifts the register from "this is about me" to "this is about them," which breaks the recognition mechanic the channel is built on — and the format bans it outright.

**10. Same angle, reworded**
- Before: five pautas that are all "procrastination is secretly fear," reshuffled.
- After: force a different taxonomy archetype and a different underlying mechanism before writing a single line.
- Why: this is the swap-test failure at scale — a viewer, and eventually a platform's duplicate/low-originality detection, can tell.

---

## 5. Prospecting Method & Pre-Publish Checklist

### From one theme to several strong hooks

1. **Name the theme** in one word or short phrase (e.g., "procrastination," "comparison," "burnout").
2. **Write down the cliché explanation** the audience already has for it — what every other account in the niche already says. This is the thing to avoid repeating.
3. **Ask what's actually underneath it, three ways:** a hidden cause (→ False Cause Reveal), a hidden function or payoff (→ Mislabel Correction: what is this behavior secretly protecting?), a hidden cost (→ Delayed Consequence: what does this quietly compound into?).
4. **Draft one hook per answer**, each using a different archetype from Section 2. One theme now produces 3 structurally distinct candidates instead of 3 rewordings.
5. **Score each against the Section 1 rubric.** Discard anything averaging under ~6, or that a competitor could publish unchanged.
6. **Build the script backward from the closing image**, not forward from an explanation — decide what the last frame looks or feels like first, then write the 3 lines that earn it.
7. **Run the checklist below** before finalizing.

### Pre-publish checklist

1. Under 88 characters — ideally 40–60?
2. No ending period, no rhetorical question?
3. Names one specific behavior or moment, not a category or trait?
4. Contradicts something the viewer currently believes about themselves?
5. Passes the swap test — no other account in the niche could post it unchanged?
6. Zero banned content: no promised outcome, no health/money/medical claim, no real name/brand/news, no "watch till the end"?
7. Reads as a complete, standalone provocation needing no context — and the last line closes on an image, not a summary?
8. Fits the 8–12s budget once read aloud, pauses included?

---

## Sources

**Curiosity, attention & memory mechanics**
- Loewenstein, G. (1994). *The Psychology of Curiosity: A Review and Reinterpretation.* Psychological Bulletin — https://www.cmu.edu/dietrich/sds/docs/loewenstein/PsychofCuriosity.pdf
- Golman, R. & Loewenstein, G. *Curiosity, Information Gaps, and the Utility of Knowledge* — https://www.cmu.edu/dietrich/sds/docs/golman/golman_loewenstein_curiosity.pdf
- Zeigarnik effect (Bluma Zeigarnik, 1927) on interrupted-task recall, discussed via a 2026 research summary — https://yukaichou.com/behavioral-analysis/zeigarnik-effect-incomplete-tasks-memory-tension/
- Concreteness effect / dual-coding (Paivio) and its effect on social sharing — https://journals.sagepub.com/doi/10.1177/17470218251392831 and https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1718655/full
- Pattern interrupt and the orienting response — https://www.th3design.co.uk/2025/11/pattern-interrupts-in-marketing/

**Short-form retention mechanics**
- TrueFuture Media, *The Science of the Short-Form Video Hook* (synthesizes YouTube/TikTok/Instagram ranking-signal documentation plus Itti & Baldi 2009, Kang et al. 2009, Lang 2000) — https://www.truefuturemedia.com/articles/science-of-short-form-video-hooks
- OpusClip, *YouTube Shorts Hook Formulas* (buried lede, slow build as retention killers) — https://www.opus.pro/blog/youtube-shorts-hook-formulas
- Percee Digital, *The 3-Second Rule* (Meta/TikTok first-3-second hold-rate data) — https://www.perceedigital.com/insights/video-hooks-that-convert/

**Platform policy & distribution mechanics**
- YouTube Help, Spam Policy — malicious clickbait definition — https://support.google.com/youtube/answer/2801973
- 1of10, *What is a Clickbait Thumbnail* — high-CTR/low-satisfaction pattern — https://1of10.com/blog/clickbait-thumbnail/
- AuditSocials, *TikTok Community Guidelines 2026* — engagement-bait suppression mechanics — https://www.auditsocials.com/platforms/tiktok-community-guidelines

**Narration pacing**
- ViralMint, Video Script Length Calculator — wpm ranges by narration style — https://viralmint.net/tools/video-script-length-calculator/
- VoiceoverGuy — dramatic/emotional read pacing vs. energetic pacing — https://www.voiceoverguy.co.uk/voice-over-word-count-calculator
