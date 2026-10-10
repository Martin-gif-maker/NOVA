"""A small library and three kinds of questions, used to check that searching by meaning helps and never hurts."""

# (file name, text) - the first twelve are what the questions are about, the rest is other material
PASSAGES = [
    ("lease.txt", "The tenant pays a security deposit equal to two monthly rents before moving in. It is returned within 30 days after the lease ends."),
    ("contract.txt", "Either party may terminate this agreement by giving ninety days written notice to the other party."),
    ("warranty.txt", "The warranty covers manufacturing defects for 24 months and does not cover damage caused by water or drops."),
    ("handbook.txt", "Our office is closed on public holidays. Employees receive 25 days of paid annual leave per calendar year."),
    ("report.txt", "The quarterly revenue rose to 4.2 million euro, driven mainly by subscription renewals in the German market."),
    ("router.txt", "To reset the router, hold the small button on the back for ten seconds until the light blinks orange."),
    ("prescription.txt", "The patient should take one tablet twice a day after meals and avoid alcohol during the treatment."),
    ("travel.txt", "Flights to Lisbon depart every morning at 7:40 from terminal two; check-in closes forty minutes before departure."),
    ("recipe.txt", "The recipe needs 300 grams of flour, two eggs, a pinch of salt and half a litre of milk for the pancakes."),
    ("invoice.txt", "Invoices are payable within fourteen days; late payments incur interest of one percent per month."),
    ("museum.txt", "The museum opens at ten o'clock and admission is free for children under the age of twelve."),
    ("backup.txt", "Backups run every night at 2 am and are kept for thirty days on an encrypted server in Frankfurt."),
    ("garden.txt", "Tomato seedlings should be planted outdoors after the last frost, about half a metre apart, in full sun."),
    ("car.txt", "Check the tyre pressure once a month and change the engine oil every fifteen thousand kilometres."),
    ("school.txt", "Parents' evening takes place on the first Thursday of November in the main hall of the school."),
    ("gym.txt", "Membership includes access to the swimming pool and group classes; the sauna costs extra."),
    ("printer.txt", "If the printer shows a paper jam, open the rear cover and remove the sheet slowly with both hands."),
    ("insurance.txt", "The policy covers theft of a bicycle only if it was locked to a fixed object with an approved lock."),
    ("meeting.txt", "The steering committee decided to postpone the product launch until the security audit is complete."),
    ("history.txt", "The bridge was built in 1874 and survived two floods before it was widened for trams in 1931."),
    ("hiking.txt", "The trail to the summit takes about four hours; carry at least two litres of water per person."),
    ("coffee.txt", "For a French press use coarsely ground beans and let the coffee steep for four minutes before pressing."),
    ("pets.txt", "Puppies need their first vaccination at eight weeks and a booster four weeks later."),
    ("energy.txt", "The heat pump uses about a third of the electricity that the old radiators needed."),
    ("library.txt", "Books can be borrowed for three weeks and renewed twice unless another reader has reserved them."),
    ("tax.txt", "The tax return for the previous year must be filed by the end of April; an extension is possible on request."),
    ("phone.txt", "The mobile plan includes twenty gigabytes of data per month and unlimited calls within the country."),
    ("wedding.txt", "The ceremony starts at three in the afternoon in the old town hall, followed by dinner at the vineyard."),
    ("course.txt", "The beginners' Spanish course runs for twelve weeks, with one ninety-minute lesson every Tuesday evening."),
    ("paint.txt", "Apply two coats of primer to bare wood and let each coat dry for six hours before sanding lightly."),
]

# reworded: the question avoids the passage's own key words
REWORDED = [
    ("How much money do I have to put down up front for the flat?", "lease.txt"),
    ("How long in advance must I tell them if I want to cancel the contract?", "contract.txt"),
    ("Will they fix my phone for free if I spilled coffee on it?", "warranty.txt"),
    ("How much vacation do staff get?", "handbook.txt"),
    ("How did sales do last quarter?", "report.txt"),
    ("My internet box is stuck, how do I restart it to factory state?", "router.txt"),
    ("How often should I swallow the pills, and can I drink wine?", "prescription.txt"),
    ("When does the plane to Portugal leave?", "travel.txt"),
    ("What ingredients do I need for crepes?", "recipe.txt"),
    ("What happens if I pay the bill late?", "invoice.txt"),
    ("Do kids have to buy a ticket to the exhibition?", "museum.txt"),
    ("How long are copies of our data stored?", "backup.txt"),
]

# exact: the question uses the passage's own words (searching by words already gets these right)
EXACT = [
    ("security deposit two monthly rents", "lease.txt"),
    ("ninety days written notice", "contract.txt"),
    ("warranty manufacturing defects 24 months", "warranty.txt"),
    ("paid annual leave days", "handbook.txt"),
    ("quarterly revenue 4.2 million", "report.txt"),
    ("reset the router button", "router.txt"),
    ("tablet twice a day after meals", "prescription.txt"),
    ("flights to Lisbon terminal two", "travel.txt"),
    ("grams of flour pancakes", "recipe.txt"),
    ("late payments interest", "invoice.txt"),
    ("museum admission children", "museum.txt"),
    ("backups encrypted server Frankfurt", "backup.txt"),
]

# nothing in the library answers these
ABSENT = [
    "What is the capital of Australia?",
    "Who won the football world cup in 1998?",
    "How do I knit a scarf?",
    "What is the boiling point of mercury?",
]
