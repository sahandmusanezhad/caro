# Roadmap — everything left, in order

What is left until the end of the project, kept current. Each item says what
is true now, where it was recorded, who does it, what has to come first, and
what closes it. An open item goes into code only after it has been measured:
the predictions are written first, the measurement is run, the owner decides
on it, and the change goes in, in its own commit
([WORKING_AGREEMENT](WORKING_AGREEMENT.md)).

Last revised 2026-10-30.

Who does what:

- **The owner** starts every live request to a source, on his own machine;
  makes every choice of technology, of a rule about Persian, and of product;
  pushes; and decides what is sent where.
- **The deploy holder** owns the Vercel project and makes every change there
  (D78). The owner passes him the steps.
- **A session** — an assistant working on the owner's machine, or one that
  hands him commits to apply — measures, builds what the owner has chosen,
  commits under his name, writes the D-entry once his push is seen, and stops
  before the push.

## Where it stands against the brief

The brief asks for: **crawl offers → normalize messy data → rank by user
intent → explain the best choice**.

| Requirement | State |
|---|---|
| crawl offers | ⚠️ **one source.** Four `BamaAdapter` runs are published — run11 (2026-09-10), run13 (2026-10-06), run14 (2026-10-11) and run16 (2026-10-15), 76, 74, 77 and 73 listings — and the API serves run16 by default. `DivarCarAdapter` has its robots gate, its pause and its stop on a block, and its category-page extraction (`caro/ingest/divar_page.py`), written offline on 2026-10-26 from what the probe printed (a JSON-LD list of 24 vehicles, and the 24 cards beside it); it has read the owner's saved copy of that page once (24 of 24 listings; see the product gaps, item 1), and its live path has never run. Sheypoor and Khodro45 have adapters since 2026-10-29, written offline against one saved list page each; neither has run live. `scripts/page_probe.py` was the first step for all three. |
| normalize messy data | ✅ **built.** Persian numerals and amount words, toman and rial, mileage, Jalali and Gregorian years, make/model aliases, trim, gearbox, fuel, colour, body condition from free text, and the province. |
| rank by user intent | ⚠️ **built, not served on real data.** `caro/ranking.py` parses Persian intent, filters, relaxes and scores. No estimator has cleared the acceptance gate on a real corpus (D43), so the site shows evidence, not a ranking. |
| explain the best choice | ✅ **built.** |
| deployed | ✅ **from each push to `main`.** https://caro-rho.vercel.app — one Vercel project of two services (D64) — served the last push, `831b28e`, when it was read on 2026-10-25 (D84); see «Deploying» below. |

## The order of work

The items below, in the order they are meant to be done. Each one names the
section that holds its detail.

1. **The next D-entry, once this round is pushed.** A session. First: the
   owner pushes the four commits of 2026-10-25 (D84, the README, this roadmap,
   the working agreement). Closes when both repositories hold them, CI is
   green on the tip of the push, `/about` states 84 decisions, and the next
   entry records the push with his hashes, as D84 does for the nine commits
   before it.
2. **The floor topics** — the other words for a floor, the bare «X به بالا»,
   ranges, and the negated floor (the parser, item 5). A session measures and
   builds; the owner decides each. The first is built and waits for its push;
   three are left. Closes each when its round is recorded in a D-entry after
   the push.
3. **CI's warnings** (operations, item 1). The owner decides; a session builds
   and measures on CI.
4. **A first live run of `DivarCarAdapter`** (the product gaps, item 1). The
   owner, on his machine, after the review it names. The probe is done, the
   extraction is written and has read one saved page; what is left is the
   odd cases and the brands it lists (`first_run.py --page <the saved file>`),
   a probe of `?page=2`, and then the run. The run's plan and its predictions
   are written: [RUN_PLAN_DIVAR_FIRST](RUN_PLAN_DIVAR_FIRST.md).
5. **A larger real corpus, and collection over time** (the product gaps, item
   1). The owner runs it; a session writes the run's plan and predictions and
   reads what comes back.
6. **Sheypoor and Khodro45** (the product gaps, item 1). The owner probes;
   a session builds the adapter offline from what the probe kept. Both are
   built (2026-10-29), against the owner's saved pages: Khodro45's list,
   Sheypoor's list and two of its listing pages, whose year and odometer the
   list does not give. The offline reads have been made and acted on (the
   plan's addendum); what is left is the first live runs. The plan and its
   predictions: [RUN_PLAN_KHODRO45_SHEYPOOR](RUN_PLAN_KHODRO45_SHEYPOOR.md).
7. **An estimator that clears the gate on real data** (the product gaps, item
   2). A session, on the corpus of step 5. It is what reopens the ranked
   path's two items (the parser, items 1 and 2), compare's gated branch, and
   the calibration of the confidence policy (the product gaps, item 6).
8. **The product additions** — accident damage from listing photos, a login
   by authenticator, and the contact inbox on the deployed site (the product
   gaps, items 3, 4 and 5). The owner decides each design first. The
   options for accounts, payment and the operator's login are written, each
   with what it needs from him and the one a session recommends:
   [ACCOUNTS_AND_PAYMENT](ACCOUNTS_AND_PAYMENT.md).
9. **The demo** (the end). The last: the demo script brought up to date with
   the site as it is, recorded, and sent where the owner decides.

Steps 1 to 3 need no live request and no new decision about data; 4 to 6 are
the owner's live runs; 7 depends on 5; 8 and 9 can wait for 7, or not, as
the owner chooses.

## The parser — open, recorded

1. **The ranked path's red lines — blocked by a real estimator** (D43, D66).
   `_passes` in `caro/ranking.py` has no rule for `manual` or `repaint` and
   lets an unknown through all four; the evidence path judges all four and
   holds an unknown apart (`webapp/api/constraints.py`). Measured on
   SYNTHETIC and left as it is: its rows carry none of the fields the
   evidence rules read, and swapping `_passes` alone sends an unknown into
   budget and odometer relaxation and an empty shortlist (D66). It reopens
   when all three hold: an estimator clears the acceptance gate on a real
   corpus; the rows real ranking scores carry the evidence the four rules
   read; and the measurement is run again — met, broken and unknown, the
   shortlist, the relaxation ladder, and the comparison with price-sort. No
   commit makes the ranked path evidence-aware before then.

2. **The ranked path's province — blocked with the first** (D43, D82). A
   query that names a province is a constraint on the evidence path
   (`webapp/api/constraints.py`). `_passes` has no rule for it, because an
   appraisal `Row` carries no province, so wherever the ranking is served a
   spec that names one is not narrowed. Today that is the SYNTHETIC corpus
   alone, where the intent panel lists «استان» as understood and the
   shortlist is the one without it. It is left as it is, as the red lines
   are, and pinned: `tests/test_ranking.py` turns red the day a `Row`
   carries a province or `_passes` reads one, and `tests/test_api_contract.py`
   section 18 the day a published corpus is ranked. It reopens with the
   first item: an estimator clears the gate on a real corpus, the rows
   ranking scores carry a province, and what an unknown province does there
   — held apart, as on the evidence path, or let through — is measured and
   decided before it is written.

3. **Reading the place a buyer writes — what is not covered** (D82). The
   reader takes a full province name, with a locative («در», «توی», «ساکن»,
   «استان») or without, and declines what is not a place the car should be
   in: a negation before or after the name («غیر از تهران», «تهران
   نباشه»), a nearness («نزدیک», «اطراف»), a plate («پلاک»), «خراسان» or
   «آذربایجان» alone, which begin several names, and «خلیج فارس», which
   holds one. What it declines stays under «نفهمیدیم». It was built and
   checked on constructed phrasings: no log of what buyers write exists, so
   how they write a place is not measured. Known, and left:
   - A province's name inside a longer name that is not a place is read as
     the province, with the assumption shown: «کرمان موتور», «یزد خودرو»,
     «گیلان خودرو». «خلیجفارس» with no space is not matched at all, and
     «خلیجِ فارس» typed with a kasra is read as the province, since a
     diacritic is not stripped.
   - A city (مشهد, شیراز, کرج) is not read (D74). In a clause that names a
     model it was dropped without a word, because such a clause is taken
     as understood whole: of 350 phrasings of 35 cities, 10 were listed
     under «نفهمیدیم» and 340 dropped (D83). A cue the reader already
     knows («در», «توی», «ساکن», «اطراف», «نزدیک به», «غیر از», «پلاک» …) is
     now listed with the one or two words after it, past «شهر» and
     «استان»: «در مشهد», «ساکن در شهر بندر عباس», and «پلاک ملی در مشهد» as
     two, «پلاک ملی» and «در مشهد». So is one after a budget's amount, which
     the budget clause used to take whole (item 4). Nothing is read from it;
     the page says the city was seen and not used, and the province panel
     and the ranked path are as they were. On the prototype it shows the
     city in 220 of the 350 phrasings. Known, and left, each pinned by a
     test so that it changes on purpose: a city no cue stands before
     («پراید مشهد»); a second one after « و » or «یا», where «یا» is itself
     taken as the second word of «در مشهد یا»; and «نه» and «بدون», which
     the reader knows and this does not, so «پراید نه مشهد» is still
     dropped. And any word after a cue that is no place is listed all the
     same, unless it is one of the three the stoplist holds: «حد», «حال»,
     «بودجه».
   - «تهرانپارس» adds the model `pars`, because the alias is matched as a
     substring; «پارس‌آباد» does the same, «شاهین‌شهر» adds `shahin` and
     «شهریار» sets a commute use. None of them shows the city, and after a
     cue «تهرانپارس» lists «در تهران», the part before the alias, which
     reads as a province. It was so before D82; item 4 has the rest.

4. **What the parser drops without a word** (D83). Three ways, found while
   the cities were measured and tried on the real parser. The owner asked
   for all three to be measured before any was touched, with the predictions
   written beforehand, and each is changed only where the measurement showed
   the change clean:
   - A distance cap with no «کارکرد» before it («۲۰۶ زیر ۱۰۰ هزار کیلومتر»)
     was neither read nor listed. It is read now, in four shapes: a cap word,
     a figure and a distance word («زیر ۱۰۰ هزار کیلومتر»); the figure first
     («۱۰۰ هزار کیلومتر یا کمتر»); the distance word first («کیلومتر زیر ۱۰۰
     هزار»); and «زیر ۱۰۰k». «حداکثر» joins the «کارکرد» form. Of 20 caps
     written for it 19 are read, none wrong, and none of the 12 phrases that
     hold a distance and are no odometer, nor of the 8 that give a figure and
     no cap. With neither «هزار» nor «کارکرد» before the figure, it is a cap
     only from 10000 on: «تا ۱۰۰۰ کیلومتر دورتر» is a distance to travel and
     «وانت تا ۱۵۰۰ کیلو» a weight. Known, and left, each pinned by a test so
     that it changes on purpose, each read by nothing and, in a clause that
     names a model, listed by nothing either: a bare figure («پراید ۵۰ هزار
     کیلومتر»); a cap from 1000 to 9999 with no «هزار» and no «کارکرد»
     before it, so «تا ۵۰۰۰ کیلومتر کارکرد» too; «بیشتر از ۵۰ هزار کیلومتر
     نباشه»; and «کیلومتری» («زیر ۱۰۰ هزار کیلومتری»).
   - The budget clause takes everything after its amount up to the next
     «،», so a word after the amount went with it, and
     «پراید تا ۳۰۰ میلیون در مشهد» lost the city. The clause is still taken
     whole, and the budget and the rest of the spec are as they were; what
     stands after the amount is now read as one more clause by the rule of
     item 3, for a cue and no more, cut the way the rest of the query is
     (a year clause taken out, what was acted on blanked). Of 35 cities
     written after a budget, 35 are listed; none of the 171 queries the
     suites and the measurement hold changes; a colour, a filler, a trim
     or a unit word after the amount lists nothing, as before. Known, and
     left, each pinned by a test so that it changes on purpose: what stands
     between the cue and the amount («قیمت در مشهد ۳۰۰ میلیون») is still
     taken with the clause and dropped; and a second budget in the same
     clause lends its «تا» to the place before it, as «یا» does.
   - A model's number inside an amount or a year added a model nobody wrote:
     «دنا تا ۱۳۱۰ میلیون» added `pride`, «تیبا مدل ۱۴۰۵» added `405`. A number
     is read now only where it stands alone: in the query less its amounts
     of money, and not beside another digit. Of 2901 budgets «تیبا تا N
     میلیون» 54 added a model, and of 26 years «تیبا مدل Y» 1; none does.
     The 45 uses of a number as a model written for the measurement are all
     read, the 18 amounts and years that hold one give the models written,
     and none of the suites' 51 queries, nor of 120 ordinary sentences,
     changes. Known, and left, each pinned by a test so that it changes on
     purpose: a number after «و» that follows a scale word is the amount's
     («تا ۳۰۰ میلیون و ۲۰۶»), as it was for the budget; and a name is matched
     as ever, so «پژو۲۰۶۹» and «پژو 206 میلیون» still read 206.
   - A cue or a model alias is matched inside a longer word: «محدوده» sets a
     flexible budget, «بارفروش» a cargo use, «پارس‌آباد» the model `pars`.
     Measured, not changed, and left to the owner, since which letters may
     stand beside a word is a choice about Persian and not a measurement.
     On 69 words that hold a cue or an alias and are no use of it, and 33
     true forms that carry a suffix: no letter before it clears 30 of the
     69 and loses none of the 33, but stops reading a name with a prefix
     typed on, «وتیبا»; no letter on either side clears 63 and loses 16 of
     the 33; the same with a list of suffixes, written by hand for it,
     clears 58 and loses 2. On 2026-10-18 the owner chose to leave all three
     (D84).

   Next: each case left in items 3 and 4 is a candidate round of its own,
   and none is queued; the owner picks one, or none.

5. **The budget floor — what is read, and what is left.** A floor is a
   cue («از» or «بالای», and not the end of a word), an amount of money, and
   «به بالا», with nothing between them. A soft word may stand before the
   amount («حدود», «تقریبا»), and after it the unit that «۱ میلیارد و ۲۰۰
   میلیون» leaves and a currency word. A floor and a year are also written
   together («از ۲۰۰ میلیون مدل ۹۸ به بالا»), and then the only «به بالا» is
   the year clause's: the floor is read there too, and the year clause as it
   was. A figure with no scale word is not money, so «از ۳۰۰ به بالا» sets
   no floor and is listed under «نفهمیدیم». A floor's amount is not also the
   ceiling: the budget cues and the lone amount read the query with the
   floor's phrase blanked out, so a floor alone has no ceiling and assumes
   nothing. Two changes, each measured before it was made, in two commits;
   88 rows of `tests/test_ranking.py` pin what is read and what is left, and
   the panel prints what is read under «کف بودجه». They answer two faults
   found while the third change of item 4 was tested, and older than all
   three:
   - The text between «از» or «بالای» and the first «به بالا» went to
     `parse_amount`, which takes a bare number for millions. «از» was matched
     at the end of a word («شیراز», «اهواز», «نیاز») and as the word of «غیر
     از», and «به بالا» is also the tail of a year clause, so «پراید از مدل
     ۹۸ به بالا» set a floor of 98,000,000 and «پراید ساکن شیراز مدل ۱۴۰۱ به
     بالا» one of 1,401,000,000. Of 35 such phrases, five years after seven
     lead-ins, 35 set a floor; none does now. With words between a «از» and
     an amount, the amount that was the budget became the floor: of 128
     phrases written to show it, 128 set a floor, 96 the budget's amount and
     32 an odometer's «۱۰۰ هزار»; none does now. On run16, «پراید از مدل
     ۱۴۰۱ به بالا» matched none of the 53 Pride listings and matches 1, as
     «پراید مدل ۱۴۰۱ به بالا» does.
   - A floor was read as a ceiling too. With no cue clause the first amount
     of money is taken for the ceiling, with the assumption «عدد قیمت را
     سقف بودجه فرض کردیم» printed, and a floor's amount was that amount: of
     144 phrasings of a floor, six forms and six amounts, with no model and
     with three, 144 had it for both and 96 printed the assumption; none
     does now. On run16, «پراید از ۴۰۰ میلیون به بالا» matched none of the
     53 and matches 47 (3 have no price, 3 are below it).

   Of the 16378 queries written for the checks of the last three changes,
   162 differ from the parser before these two, each holding «به بالا» and
   each in the floor alone; none of the 171 queries the suites and the
   measurement hold changes. On 16378, 1553, 572 and 169 queries of the
   measurements and 28923 generated ones, a separate copy of the rule, kept
   outside the repository, returns what the code returns.

   Known, and left, each pinned by a test so that it changes on purpose.
   The old rule took whatever stood between the cue and «به بالا», and read
   some floors right by accident; the tied rule does not. Of 572 phrases
   written for the last measurement the floor changes on 272: on 128 it was
   the budget or an odometer's figure and is none now, and on 144 it was
   right and is no longer read: a word between the cue and the amount
   («از قیمت ۲۰۰ میلیون به بالا», and «بودجه», «مبلغ», «حدودا»; 96); the
   «از» that ends a word («شیراز ۲۰۰ میلیون به بالا»; 24); and the lower end
   of a range with a year clause («از ۲۰۰ تا ۴۰۰ میلیون مدل ۹۸ به بالا»;
   24). In the first two the amount that was the floor is the ceiling now,
   with the assumption printed where no cue clause names it: the meaning
   reversed. In the range the upper end is the ceiling, as it was. The old
   rule had paired 120 of the 144 with a wrong ceiling as well.

   Measured, not changed, and left. «بالای ۴۰۰ میلیون», without «به بالا»,
   sets no floor, and its amount is taken for the ceiling, with the
   assumption printed: the meaning reversed when a floor is meant. Of 456
   phrasings written for the measurement, 144 mean a floor («بالای X»,
   «بالای X باشه», «بالای X، سفید», and three with another requirement
   after it) and 312 a ceiling (thirteen forms of a negation: «بالای X
   نباشه», «نشه», «نره», «نیست», «نمی‌خوام» and the rest). Read as a ceiling
   it is right on 312. Read as a floor wherever it stands, it is right on
   144; a floor except where a negation the province reader already knows
   stands beside it, on 264; a floor only before a list of positive words,
   on 360. No rule reads both kinds right, and the owner chose to leave it
   as it is.

   Other words for a floor — built in part. «حداقل X», «حداقل قیمت X» and the
   suffix «X و بالاتر», «X و بیشتر», «X یا بیشتر» are a floor (`_FLOOR_L`,
   `_FLOOR_T`), tried after the two floors above; a negation right after the
   phrase (thirteen words) leaves it to the ceiling rules. Before, none was:
   of 192 phrasings of eight forms (six amounts, with no model and with three)
   all 192 had the amount for the ceiling, 168 with the note printed and the
   24 written «حداقل بودجه X» with nothing said, as were 12 of 12 written
   «حداقل قیمت X». Measured before it was built, on 1736 inputs and ten rule
   sets: of 954 phrasings with a meant reading it repairs 330 and breaks none
   that was right in the sets that hold its words; the 607 queries the
   suites hand the parser, 56 phrasings with a figure that is not money and
   119 ordinary sentences are read as before. On run16 «پراید حداقل ۴۰۰
   میلیون» matches 47 of the 53 Pride listings where it matched 3. Left, each
   pinned by a test so that it changes on purpose:
   - «حداقل بودجه X» is a ceiling, as it was: the «بودجه» cue takes the
     amount. It may say what the buyer has to spend and not the price asked,
     which is a rule about Persian and the owner's. Reading it too would
     change 66 more of the 954, the ones written to mean a floor, and break
     none; whether buyers mean a floor by it is the question.
   - «بیشتر از X», «بیش از X» and «بالاتر از X» are ceilings, as they were. They
     are the ambiguity of «بالای X». Four rules that read them were measured;
     they break 96, 144, 240 and 324 right readings of negated ceilings, and a
     guard that looks after the phrase sees none of a negation before it
     («نباید بیشتر از ۴۰۰ میلیون باشه»: 0 of 108 kept as a ceiling by the three
     without a whitelist, 36 of 108 by the one with it). The existing year
     form reads «بیشتر از X مدل Y به بالا» as a floor, through its bare «از».
   - «حداقل ۴۰۰ میلیون پول دارم», what the buyer has, is a floor (12 of 12).
     On run16 that shows 47 listings where the ceiling showed 3; that is a
     result of this corpus's prices, 66 of 69 priced listings being at or
     above 400 million, and it reverses on a corpus of cheap cars.
   - A negation outside the thirteen is not seen (0 of 36 made outside the
     list kept as a ceiling), and a number glued to a word, «پراید۴۰۰ میلیون
     و بالاتر», is not read.

   A ceiling read as a floor before a year clause — built. «پراید کمتر از ۴۰۰
   میلیون مدل ۹۸ به بالا» was a floor of 400 million and no ceiling, and nothing
   listed, because `_CUE` is the bare «از», which is the tail of «کمتر از»:
   288 of 288 made phrasings (six comparatives, six amounts, two years, four
   contexts). A floor whose cue a comparative stands right before («کمتر»,
   «پایین‌تر», «ارزان‌تر», «ارزون‌تر») is refused, and the ceiling rules read
   the query as they do for «زیر»: all 288 are a ceiling of the amount with the
   year clause as it was. 0 of the 1,104 other made phrasings change (the plain
   floor with a year clause, «بیشتر از», «بالاتر از», «بیش از», «بالای X به
   بالا», the ceilings that were right, a comparative with no year clause), and
   of 25 ordinary sentences one does, the same fault. Left: «بیشتر از» and
   «بالاتر از» still read the floor (D84); two floors in one query, and a
   floor by word beside one by cue, are not pinned.

   Not built, each measured on made phrasings and each a round of its own,
   with the predictions written first:
   - A bare «X به بالا» («پراید ۴۰۰ میلیون به بالا») is read as a ceiling,
     on 24 of 24. A rule that makes the cue optional reads it as a floor,
     and on 72 of 72 with a ceiling clause beside it («زیر ۸۰۰ میلیون،
     ۴۰۰ میلیون به بالا»). But it also reads «تا ۴۰۰ میلیون به بالا نره»
     (up to 400 million, not higher) as a floor, where the parser reads the
     ceiling it is: five of five phrases tried, and four of five when a
     negation after «به بالا» is skipped, since «نره», «نشه», «نرسه»,
     «نگذره» and «نزنه» are in no list of negations the parser holds. How
     many buyers write it that way is not known; a round on it measures the
     hazard family first.
   - A range sets no floor, on 96 of 96: «از X تا Y», «بین X تا Y» and
     «X تا Y» give the upper end as the ceiling; «از X الی Y» gives the
     lower end, with the assumption printed.
   - A negated floor, «پراید از ۴۰۰ میلیون به بالا نباشه», is read as a
     floor of 400 million with no ceiling (before: a floor and a ceiling of
     400 million): the meaning reversed, on 24 of 24. A rule that skips a
     negation after «به بالا» reads it as the ceiling, on 24 of 24.

   Next: the three topics above, one round each, in the order the owner
   picks. Each round writes its predictions first, measures on phrasings
   written for it and on the sets the last rounds used, puts the choice to
   the owner, and builds only what he chooses, with tests that pin what is
   read and what is left. The phrasings of the earlier rounds were written
   outside the repository; the forms and counts given here are enough to
   write them again.

## The product gaps

1. **Data.**
   - Divar: a first live run of `DivarCarAdapter`. Review Divar's terms and
     robots directives for the car category first, and record the finding
     whatever it says. Then probe: `scripts/page_probe.py` fetches up to five
     public pages under the same robots gate and pause, keeps them on his
     machine, and prints a skeleton that can be sent back with no digit and,
     with `--no-text`, no text in it. That was done on 2026-10-26 for
     `/s/tehran/car`; the `light` slug the adapter held answered 404, and is
     gone from its table. robots.txt was unchanged (92 bytes, four rules) and
     the page is server-rendered, so no browser is needed: the 24 listings are
     in one JSON-LD list and in the cards. The extraction is written from that
     (`caro/ingest/divar_page.py`) and has read the saved page once, by
     `first_run.py --page <the saved file>`, which prints the inventory and, in
     counts, what the parser had to assume. That first read (24 of 24 listings):
     `IRR` and `KMT` on all 24; 22 prices equal to the card's toman figure (the
     node's number is rials), 2 with no displayed price to confirm them; the damage field
     holds four values (intact 18, some-scratches 3, some-paint 2, half-paint 1)
     and is now the body condition; make and model filled on 14, because the
     table is domestic only; three prices under the 10M floor, which the
     eligibility gate did not refuse until now; three years on which the node
     and the title disagree and one odometer on which the node and the card do.
     Still to read: those four (the report lists them as numbers), what the ten
     listings outside the table are called (the report counts the brand and the
     model), and `?page=2`, which has not been asked. Only then the run: one
     city and a handful of pages; volume is not the point. `CARO_SELLER_SALT` must be set. Expect to be blocked; the adapter
     stops and says so, and that is the design. Who: the owner. Closes when
     the run's inventory is read and recorded, published or not.
   - Bama: a larger corpus. The four published runs hold 73 to 77 listings
     each, and no estimator has cleared the gate on any of them. The size and
     the spread a run needs are written down before it is collected (D35:
     acquisition and estimator do not change in the same run). Who: the
     owner runs it; a session writes the plan, the predictions and the
     promotion. Closes when a corpus is promoted and its D-entry says what
     it can and cannot judge.
   - Sheypoor and Khodro45: adapters, under the same rules — robots.txt read
     in code, no evasion, no contact details, a business badge the only
     source of a seller's type (D26). The owner probes first
     (`scripts/page_probe.py --source sheypoor --origin … --url …`); the probe's
     pages stay on his machine, and the adapter is built and tested offline
     against them. Two commands a source: the probe on the site's own home
     page and on the car list page he copies out of his browser's address bar
     (the session cannot know either address, and does not ask a site for it),
     then `page_probe.py --survey <the saved list page>`, whose whole output is
     counts, shapes and short categories and can be sent as it is. If the list
     is drawn in the browser and the page comes back empty, the same probe with
     `--render browser`, with `--wait 8` where the rows arrive after the page
     does (Khodro45's auction table is skeletons in the HTML). Sheypoor and
     Khodro45 are both Next.js; the survey reads their data stream. Closes
     when the adapter's suite runs offline and a first small live run has
     been read. The suites run offline (2026-10-29: `caro/ingest/khodro45.py`
     and `caro/ingest/sheypoor.py`, built against the owner's saved pages);
     the live runs are next.
   - `province` where the market is. run16, the corpus served, carries it
     on all 73 rows: 42 stated, 31 by a city that shares its province's
     name, where run14 had 76 of 77 and run13 34 of 74. Every line of run16
     was read before it was published, and no district named like a
     province stands behind any of its 42 stated rows (D80). The car page
     and the lists — search's tables and compare's evidence rows — draw it,
     with how it was read (D81). The search reads it (D82): «پراید در
     تهران» is a constraint like the budget, so a car in another province
     is left out, one with none is held apart and named, and the panel
     lists «استان: تهران». On run16 that is 18 matches and none apart; on
     run13, 3 matches and 31 cars apart; on run11, which holds no province,
     no match and every Pride apart. The ranked path does not read it (the
     parser, item 2).
   - Longitudinal collection. Time-dependent and unrecoverable: a day not
     collected is gone. A second discovery run is a new sample, not a
     series: on run11's pin, 26 days later, 3 of its 76 listings were drawn
     again (TEMPORAL_CONTRACT.md §10). Who: the owner, on a schedule he
     sets. Closes when a series is collected on one pin and its watch rounds
     are recorded.

2. **An estimator that clears the gate on real data** (D43). Run the ladder
   in `caro/appraisal.py` — `GlobalQuantiles`, `ComparableQuantiles`,
   `LogLinearQuantiles`, and `PartialPoolingQuantiles` — against
   `AcceptanceGate` on a larger real corpus, and report whichever wins; if it
   is the baseline, ship the baseline and say why. Until one clears, nothing
   is ranked on real data, and compare's gated branch stays unmeasurable:
   when it becomes measurable, build the three-state fixture (vehicle,
   assignment, `unknown`) and measure detail, compare alone, compare beside a
   vehicle, and search. Who: a session, on a corpus the owner collected. The
   gate is not edited after its output is seen (D35). Closes when the gate's
   verdict on a real corpus is recorded, whatever it is.

3. **Accident damage from listing photos.** Not built. When it is, its output
   is recorded as inferred, not observed, and says «قابل تشخیص نیست» when it
   cannot tell. Who: the owner chooses the model and where it runs; a
   session measures it on photos he provides before anything is shown.
   Closes when its accuracy and its refusals are measured and recorded.

4. **Authenticator-based login.** Not built. The admin view opens today with
   `CARO_ADMIN_TOKEN`, and with the token unset it does not open at all. Who:
   the owner designs it; nothing is built before he has. The options are
   written (2026-10-30, [ACCOUNTS_AND_PAYMENT](ACCOUNTS_AND_PAYMENT.md),
   «The operator's login»). Closes when the design is recorded and built,
   with its tests.

5. **Deploying.** The Vercel project is in another account than the
   owner's, and its holder deployed `main` from `Tecso-Dev/caro` on
   2026-10-14 (D78). A push to `main` deploys: `1ebbf4a` was on the site
   within about three minutes of its push on 2026-10-15 (D80), and the last
   push, `831b28e`, was on the site when it was read on 2026-10-25. Checked
   there the same day (D84):
   the contact page has its inbox off and links to the repository's Issues
   (`CARO_INBOX=off`, D68), and the car page draws the province with how it
   was read. The inbox is off because a function's disk keeps nothing; it
   can be on only where something keeps what is written, which is a choice
   for the owner and steps for the deploy holder.

6. **Calibrate the confidence policy.** The bands are judgement. With real
   data they should be revisited against observed decision quality and
   relabelled — or kept, and described honestly as policy. Who: a session,
   after item 2. Closes when the bands are measured against real decisions
   or recorded as policy.

## Operations

1. **CI's warnings.** Every run carries three: Node 20 is deprecated for
   `actions/checkout@v4` and `actions/setup-node@v4` in the web job and for
   those and `actions/setup-python@v5` in the suites job, and the build warns
   of a custom font at `webapp/web/app/layout.tsx` line 29. None fails a run.
   Moving an action to a new major version is the owner's choice; once he
   makes it, the change is a commit and a run of its own, like the pin to
   ubuntu-24.04 (D84). The font warning is a change to the site, measured by
   the build and the screens suite.
2. **After every push.** CI on both repositories, and the site read from the
   outside: `/about`'s counts, and the queries the push changed. What was
   read goes into the next D-entry.

## The end

The demo is the last item. `docs/DEMO_SCRIPT.md` was written for the
submission and last changed on 2026-10-05; it describes the site as it was
then, and is brought
up to date with the site as it is, and every number it films is either
re-derived on a clean clone or a committed transcript, as the script itself
requires. Then it is recorded, and sent where the owner decides. The README
is read once more against the tree, and the last round gets its D-entry.

## Requests

Items to add. Each one moves into a list above once it has been measured and
decided.

- **Decimal separators.** «۱/۵ میلیارد», «۱٫۵ میلیارد» (the Arabic separator,
  U+066B) and «۱،۵ میلیارد» are read as 5 billion, silently: of 20 made
  phrasings per separator (five amounts, four shapes of ceiling) 0 are read
  right, where «.» and «,» are read right on 20 of 20. `normalize_fa` folds
  neither, and «،» is also the clause separator. The panel shows the wrong
  ceiling. A round of its own, and a rule about Persian that is the owner's.

## Deliberately not planned

TCO / maintenance-cost estimates. No Iranian maintenance dataset exists, so
every component would be an invented number wearing a confidence label — the
exact fake precision this system exists to avoid. Corpus-derived reliability
signals (engine-replacement rate per model, and similar) are the grounded
substitute.
