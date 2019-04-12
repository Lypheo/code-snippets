import ass, sys
replace = [("'","’"), ("...", "…"), ("--", "–"), ("!?", "?!"), (r"\N-", r"\N –")]
quotes = ("„", "“")

with open(sys.argv[1], "r", encoding="utf-8") as f:
    doc = ass.parse(f)

even = True
for i in range(len(doc.events)):
    line = doc.events[i].text
    
    if line.startswith("-"): 
        line = line.replace("-", "– ", 1)

    for x in replace:
        line = line.replace(x[0], x[1])

    while '"' in line:
        line = line.replace('"', quotes[0], 1) if even else line.replace('"', quotes[1], 1)
        even = not even

    doc.events[i].text = line

with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write('\ufeff')
    doc.dump_file(f)