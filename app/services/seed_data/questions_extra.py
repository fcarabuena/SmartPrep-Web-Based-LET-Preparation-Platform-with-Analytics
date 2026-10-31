"""More original LET-style items (5 per topic) for demo data. Same tuple format as questions.py."""

EXTRA_QUESTIONS: dict[tuple[str, str], list[tuple]] = {
    ("Filipino", "Gramatika at Retorika"): [
        ("Alin sa mga sumusunod ang pangngalang pantangi?", "aso", "Maynila", "lungsod", "guro", "B",
         "B ang tama: ang Maynila ay tiyak na ngalan ng lugar kaya pantangi at nagsisimula sa malaking titik. Ang aso, "
         "lungsod at guro ay pangkalahatang ngalan (pambalana).", "easy", "Uri ng pangngalan"),
        ("Ano ang aspekto ng pandiwa sa pangungusap na 'Kumakain ang mga bata ng almusal'?",
         "Perpektibo", "Imperpektibo", "Kontemplatibo", "Pawatas", "B",
         "B ang tama: ang 'kumakain' ay kilos na kasalukuyang nagaganap (imperpektibo). Ang perpektibo ay naganap na, "
         "ang kontemplatibo ay gaganapin pa, at ang pawatas ay anyong 'kumain' na walang aspekto.", "medium",
         "Aspekto ng pandiwa"),
        ("Alin ang wastong gamit ng 'nang'?", "Pumunta siya nang paaralan.", "Tumakbo siya nang mabilis.",
         "Ang aklat nang bata ay nawala.", "Bumili siya nang tinapay.", "B",
         "B ang tama: ginagamit ang 'nang' bago ang pang-abay na pamaraan (mabilis). Sa A, C at D dapat 'ng' dahil "
         "pananda ito ng layon o pagmamay-ari.", "medium", "Wastong gamit ng salita"),
        ("Ano ang kasingkahulugan ng salitang 'marikit'?", "maganda", "malungkot", "matapang", "marumi", "A",
         "A ang tama: ang marikit ay nangangahulugang maganda. Ang ibang pagpipilian ay may ibang kahulugan.", "easy",
         "Talasalitaan"),
        ("Anong uri ng pangungusap ayon sa gamit ang 'Naku! Nahulog ang bata!'?", "Paturol", "Patanong", "Padamdam",
         "Pautos", "C",
         "C ang tama: nagpapahayag ito ng matinding damdamin at nagtatapos sa tandang padamdam. Ang paturol ay "
         "nagsasalaysay, ang patanong ay nagtatanong, at ang pautos ay nag-uutos.", "easy", "Uri ng pangungusap"),
    ],
    ("Science", "Chemistry"): [
        ("What is the chemical symbol of sodium?", "S", "So", "Na", "Sd", "C",
         "C is correct: sodium's symbol Na comes from its Latin name natrium. S is sulfur; So and Sd are not elements.",
         "easy", "Elements and symbols"),
        ("A solution has a pH of 3. It is:", "strongly basic", "neutral", "acidic", "slightly basic", "C",
         "C is correct: pH below 7 is acidic and 3 is fairly strong. 7 is neutral and values above 7 are basic.", "easy",
         "Acids and bases"),
        ("Which of the following is a chemical change?", "Melting ice", "Dissolving sugar in water", "Burning wood",
         "Cutting paper", "C",
         "C is correct: burning forms new substances (ash, carbon dioxide, water). The others change only form or "
         "state, so they are physical changes.", "easy", "Physical and chemical changes"),
        ("The atomic number of an element is equal to the number of its:", "neutrons", "protons", "nucleons",
         "electron shells", "B",
         "B is correct: the atomic number is the number of protons and identifies the element. Nucleons are protons "
         "plus neutrons (mass number).", "easy", "Atomic structure"),
        ("The formula H₂O shows that one water molecule contains:", "2 hydrogen atoms and 1 oxygen atom",
         "1 hydrogen atom and 2 oxygen atoms", "2 hydrogen atoms and 2 oxygen atoms",
         "a mixture of hydrogen gas and oxygen gas", "A",
         "A is correct: the subscript 2 belongs to hydrogen; oxygen has an implied subscript of 1. Water is a compound, "
         "not a mixture of gases.", "easy", "Chemical formulas"),
    ],
    ("Science", "Physics"): [
        ("What is the SI unit of force?", "joule", "newton", "watt", "pascal", "B",
         "B is correct: force is measured in newtons (kg·m/s²). The joule measures energy, the watt power and the pascal "
         "pressure.", "easy", "Units of measurement"),
        ("A jeepney travels 120 km in 2 hours. What is its average speed?", "240 km/h", "60 km/h", "30 km/h",
         "122 km/h", "B",
         "B is correct: average speed = distance ÷ time = 120 ÷ 2 = 60 km/h. A multiplies instead of dividing.", "easy",
         "Motion"),
        ("'For every action there is an equal and opposite reaction' is Newton's:", "first law", "second law",
         "third law", "law of universal gravitation", "C",
         "C is correct: this is the third law. The first law is inertia, the second is F = ma.", "easy", "Laws of motion"),
        ("Which color of visible light has the longest wavelength?", "Violet", "Blue", "Green", "Red", "D",
         "D is correct: red light has the longest wavelength (about 700 nm) and violet the shortest.", "medium",
         "Waves and light"),
        ("What is the unit of electrical resistance?", "ampere", "volt", "ohm", "coulomb", "C",
         "C is correct: resistance is measured in ohms. Amperes measure current, volts potential difference and "
         "coulombs charge.", "easy", "Electricity"),
    ],
    ("Social Science", "Philippine History"): [
        ("Who wrote the novel 'Noli Me Tangere'?", "Andres Bonifacio", "Jose Rizal", "Marcelo H. del Pilar",
         "Apolinario Mabini", "B",
         "B is correct: Jose Rizal published the Noli in 1887. Bonifacio founded the Katipunan, del Pilar edited La "
         "Solidaridad, and Mabini wrote 'El Verdadero Decálogo'.", "easy", "Propaganda Movement"),
        ("Philippine independence from Spain was proclaimed in Kawit, Cavite on:", "June 12, 1898", "July 4, 1946",
         "August 26, 1896", "December 30, 1896", "A",
         "A is correct: Aguinaldo proclaimed independence on June 12, 1898. July 4, 1946 is independence from the United "
         "States; August 1896 is the Cry of Pugad Lawin; December 30, 1896 is Rizal's execution.", "easy",
         "Philippine Revolution"),
        ("What secret revolutionary society did Andres Bonifacio found in 1892?", "La Liga Filipina", "Katipunan",
         "Propaganda Movement", "Malolos Congress", "B",
         "B is correct: the Katipunan aimed at independence through revolution. La Liga Filipina was Rizal's civic "
         "association; the Propaganda Movement sought reforms; the Malolos Congress came in 1898.", "easy",
         "Philippine Revolution"),
        ("Which 1872 event led to the execution of the priests Gomez, Burgos and Zamora (GOMBURZA)?", "Cavite Mutiny",
         "Battle of Mactan", "Cry of Pugad Lawin", "Tejeros Convention", "A",
         "A is correct: the Spanish blamed the three priests for the Cavite Mutiny of 1872. Mactan was in 1521, Pugad "
         "Lawin in 1896, and Tejeros in 1897.", "medium", "Spanish colonial period"),
        ("The First Philippine Republic was inaugurated in:", "Manila", "Malolos, Bulacan", "Kawit, Cavite",
         "Biak-na-Bato, Bulacan", "B",
         "B is correct: the Malolos Republic was inaugurated at Barasoain Church on January 23, 1899. Biak-na-Bato was a "
         "short-lived republic of 1897.", "medium", "Philippine Revolution"),
    ],
    ("Curriculum Development", "Curriculum Concepts and Types"): [
        ("The curriculum that teachers actually deliver in the classroom is the:", "recommended curriculum",
         "written curriculum", "taught curriculum", "hidden curriculum", "C",
         "C is correct: the taught curriculum is what teachers implement daily. The recommended curriculum comes from "
         "experts or agencies, the written one is in documents, and the hidden one is learned implicitly.", "easy",
         "Types of curriculum"),
        ("The 'hidden curriculum' refers to:", "unplanned values and norms learned implicitly from school life",
         "lessons removed from the syllabus", "the content of examinations kept secret",
         "a special curriculum for gifted learners", "A",
         "A is correct: the hidden curriculum consists of attitudes and norms absorbed through school culture rather "
         "than formal lessons.", "easy", "Types of curriculum"),
        ("Ralph Tyler's rationale for curriculum development begins with:", "determining the purposes or objectives",
         "selecting textbooks", "evaluating learning outcomes", "organizing learning experiences", "A",
         "A is correct: Tyler's first question asks what educational purposes the school should seek to attain. "
         "Selecting, organizing and evaluating learning experiences follow.", "medium", "Curriculum models"),
        ("Curriculum guides and course syllabi are examples of the:", "written curriculum", "taught curriculum",
         "learned curriculum", "hidden curriculum", "A",
         "A is correct: documents that specify what should be taught make up the written curriculum. The taught, learned "
         "and hidden curricula happen in practice.", "easy", "Types of curriculum"),
        ("Bruner's spiral curriculum means that:", "topics are revisited with increasing depth and complexity",
         "each topic is taught only once in depth", "subjects are taught separately with no links",
         "learners choose all topics themselves", "A",
         "A is correct: a spiral curriculum returns to key ideas across grade levels, building on prior learning.",
         "medium", "Curriculum design"),
    ],
    ("Classroom Management", "Discipline Approaches"): [
        ("Canter's Assertive Discipline emphasizes:", "clear rules with consistent consequences and positive recognition",
         "ignoring all misbehavior", "punishments decided only by students", "physical punishment for serious offenses", "A",
         "A is correct: the teacher states expectations firmly, applies consequences consistently and recognizes good "
         "behavior. Physical punishment is never appropriate.", "easy", "Discipline models"),
        ("Kounin's concept of 'withitness' means that the teacher:", "is aware of everything happening in the classroom",
         "uses humor to keep attention", "grades strictly", "changes the seating plan often", "A",
         "A is correct: withitness is communicating awareness of what all students are doing, which prevents "
         "misbehavior from escalating.", "medium", "Classroom management"),
        ("Dreikurs' logical consequences are best described as:", "related, respectful and reasonable outcomes of behavior",
         "arbitrary punishments", "rewards for good behavior", "ignoring the behavior completely", "A",
         "A is correct: logical consequences connect directly to the misbehavior (e.g., cleaning up a mess one made).",
         "medium", "Discipline models"),
        ("A learner is briefly off-task during group work. What is the most appropriate first response?",
         "Move closer or give a nonverbal cue", "Send the learner to the principal",
         "Reprimand the learner in front of the class", "Call the parents immediately", "A",
         "A is correct: low-key interventions such as proximity and eye contact redirect minor behavior without "
         "disrupting the lesson. The other responses are excessive for minor off-task behavior.", "easy",
         "Responding to misbehavior"),
        ("Under DepEd's Child Protection Policy (DO 40, s. 2012), corporal punishment of learners is:",
         "allowed for serious offenses", "prohibited", "allowed with parents' consent", "allowed for older learners", "B",
         "B is correct: the policy prohibits corporal punishment and other degrading forms of discipline in all "
         "circumstances.", "easy", "Child protection"),
    ],
    ("Teaching Methods", "Educational Technology"): [
        ("TPACK describes the integration of which kinds of teacher knowledge?", "Technology, pedagogy and content",
         "Testing, planning and assessment", "Theory, practice and curriculum", "Tools, programs and computers", "A",
         "A is correct: TPACK is Technological Pedagogical Content Knowledge — using technology in ways that fit both "
         "the content and the teaching approach.", "easy", "Technology integration"),
        ("In the SAMR model, which level describes technology that allows new tasks that were previously inconceivable?",
         "Substitution", "Augmentation", "Modification", "Redefinition", "D",
         "D is correct: redefinition is the highest level. Substitution and augmentation enhance tasks; modification "
         "significantly redesigns them.", "medium", "Technology integration"),
        ("Which of the following is an asynchronous learning tool?", "Live video conference", "Discussion forum",
         "Phone call", "Face-to-face lecture", "B",
         "B is correct: forum participants post and reply at different times. The other options require everyone to "
         "participate at the same time.", "easy", "Online learning"),
        ("Fair use allows a teacher to:", "use limited portions of copyrighted works for educational purposes under conditions",
         "copy entire textbooks for all students freely", "sell copies of copyrighted materials",
         "remove the author's name from materials", "A",
         "A is correct: fair use permits limited, attributed educational use. Wholesale copying, selling and removing "
         "attribution violate copyright.", "medium", "Copyright and ethics"),
        ("Which is a main function of a learning management system (LMS)?",
         "Distribute materials, collect work and track learner progress", "Replace teachers completely",
         "Only host live video calls", "Repair school computers", "A",
         "A is correct: an LMS organizes course content, submissions and progress data. It supports rather than "
         "replaces teachers.", "easy", "Educational technology tools"),
    ],
    ("Foundations of Education", "Legal Bases of Philippine Education"): [
        ("Republic Act 7836 is known as the:", "Philippine Teachers Professionalization Act of 1994",
         "Enhanced Basic Education Act of 2013", "Magna Carta for Public School Teachers",
         "Governance of Basic Education Act of 2001", "A",
         "A is correct: RA 7836 created the Licensure Examination for Teachers. K to 12 is RA 10533, the Magna Carta is "
         "RA 4670, and RA 9155 is the Governance Act.", "easy", "Laws on teaching"),
        ("The Enhanced Basic Education Act of 2013 (K to 12) is:", "Republic Act 10533", "Republic Act 9155",
         "Republic Act 7722", "Republic Act 4670", "A",
         "A is correct: RA 10533 institutionalized K to 12. RA 7722 created CHED; RA 9155 and RA 4670 are noted above.",
         "easy", "Laws on basic education"),
        ("The Magna Carta for Public School Teachers is:", "Republic Act 4670", "Republic Act 7836",
         "Republic Act 10533", "Batas Pambansa Blg. 232", "A",
         "A is correct: RA 4670 (1966) protects the rights and welfare of public school teachers. BP 232 is the Education "
         "Act of 1982.", "easy", "Laws on teaching"),
        ("Republic Act 9155 is the:", "Governance of Basic Education Act of 2001", "Kindergarten Education Act",
         "Philippine Teachers Professionalization Act", "Higher Education Act of 1994", "A",
         "A is correct: RA 9155 renamed DECS to DepEd and set the governance of basic education. The Higher Education Act "
         "is RA 7722.", "medium", "Laws on basic education"),
        ("Under Article XIV of the 1987 Constitution, the State maintains a system of free public education in the:",
         "elementary level only", "elementary and high school levels", "college level only", "graduate level", "B",
         "B is correct: Section 2(2) provides free public education in the elementary and high school levels.",
         "medium", "Constitutional provisions on education"),
    ],
    ("Science/Biology Major", "Cell Biology and Genetics"): [
        ("In which phase of mitosis do chromosomes line up at the cell's equator?", "Prophase", "Metaphase",
         "Anaphase", "Telophase", "B",
         "B is correct: chromosomes align on the metaphase plate. They condense in prophase, separate in anaphase, and "
         "nuclei re-form in telophase.", "easy", "Cell division"),
        ("DNA replication is called semiconservative because:", "each new DNA molecule has one old and one new strand",
         "only half of the DNA is copied", "both strands are newly made", "the original molecule is destroyed", "A",
         "A is correct: each parental strand serves as a template, so every daughter molecule keeps one original strand.",
         "medium", "Molecular genetics"),
        ("Which organelle contains digestive enzymes that break down worn-out cell parts?", "Lysosome", "Ribosome",
         "Centriole", "Nucleolus", "A",
         "A is correct: lysosomes hold hydrolytic enzymes. Ribosomes make proteins, centrioles help organize spindle "
         "fibers, and the nucleolus makes ribosomal RNA.", "easy", "Cell structure"),
        ("A dihybrid cross AaBb × AaBb (independent assortment, complete dominance) gives which phenotypic ratio?",
         "9:3:3:1", "3:1", "1:2:1", "1:1:1:1", "A",
         "A is correct: two independent 3:1 ratios combine into 9:3:3:1. 3:1 is a monohybrid ratio, 1:2:1 a genotypic "
         "ratio, and 1:1:1:1 comes from a test cross.", "medium", "Mendelian genetics"),
        ("A codon consists of how many nucleotides?", "2", "3", "4", "64", "B",
         "B is correct: a codon is a triplet of nucleotides. There are 64 possible codons, which is why D is a common "
         "distractor.", "easy", "Protein synthesis"),
    ],
    ("Social Studies Major", "Geography"): [
        ("Which imaginary line is at 0° latitude?", "Prime Meridian", "Equator", "Tropic of Cancer",
         "International Date Line", "B",
         "B is correct: the Equator is 0° latitude. The Prime Meridian is 0° longitude; the Tropic of Cancer is about "
         "23.5° N; the Date Line is near 180° longitude.", "easy", "Map and globe skills"),
        ("Which is the largest ocean on Earth?", "Atlantic", "Indian", "Pacific", "Arctic", "C",
         "C is correct: the Pacific Ocean is the largest and deepest ocean.", "easy", "Physical geography"),
        ("The Philippines lies along a zone of frequent earthquakes and volcanic eruptions called the:",
         "Pacific Ring of Fire", "Mid-Atlantic Ridge", "Great Rift Valley", "Alpide Belt", "A",
         "A is correct: the Philippines is part of the Pacific Ring of Fire, which circles the Pacific basin.", "easy",
         "Philippine geography"),
        ("What is the longest river in the Philippines?", "Agusan River", "Cagayan River", "Pampanga River",
         "Pasig River", "B",
         "B is correct: the Cagayan River in northern Luzon is the longest. The Agusan is the longest in Mindanao.",
         "medium", "Philippine geography"),
        ("On a map with a scale of 1:50,000, 1 cm on the map represents:", "50 m", "500 m", "5 km", "50 km", "B",
         "B is correct: 50,000 cm = 500 m. The other options misplace the decimal when converting centimeters.", "medium",
         "Map scale"),
    ],
    ("TLE Major", "Entrepreneurship"): [
        ("A business reaches its break-even point when:", "total revenue equals total costs",
         "sales exceed the previous year's", "fixed costs are zero", "the product is sold out", "A",
         "A is correct: at break-even there is neither profit nor loss.", "easy", "Business finance"),
        ("In a SWOT analysis, the letters stand for:", "Strengths, Weaknesses, Opportunities, Threats",
         "Sales, Wages, Orders, Taxes", "Strategy, Work, Output, Time", "Supply, Want, Offer, Trade", "A",
         "A is correct: strengths and weaknesses are internal factors; opportunities and threats are external.", "easy",
         "Business planning"),
        ("A product sells for ₱50 and costs ₱30 per unit to make. Fixed costs are ₱2,000. How many units must be sold to break even?",
         "40", "67", "100", "200", "C",
         "C is correct: contribution margin = 50 − 30 = ₱20 per unit; 2,000 ÷ 20 = 100 units. B divides by 30 and A "
         "divides by 50.", "medium", "Break-even analysis"),
        ("Which of the following is a variable cost?", "Monthly rent", "Raw materials", "Business permit", "Insurance", "B",
         "B is correct: raw materials change with the number of units produced. Rent, permits and insurance are fixed.",
         "easy", "Costing"),
        ("A target market is:", "the specific group of customers a business aims to serve", "all people in the country",
         "the business's competitors", "the place where goods are stored", "A",
         "A is correct: a target market is a defined customer segment the business designs its offer for.", "easy",
         "Marketing"),
    ],
    ("Filipino Major", "Panitikan"): [
        ("Sino ang may-akda ng 'Florante at Laura'?", "Jose Rizal", "Francisco Balagtas", "Lope K. Santos",
         "Amado V. Hernandez", "B",
         "B ang tama: isinulat ni Francisco Balagtas ang 'Florante at Laura'. Kilala si Rizal sa Noli at Fili, si Santos "
         "sa 'Banaag at Sikat', at si Hernandez sa 'Mga Ibong Mandaragit'.", "easy", "Mga akda at may-akda"),
        ("Ang 'Ibong Adarna' ay halimbawa ng:", "korido", "awit", "epiko", "dalit", "A",
         "A ang tama: ang korido ay may wawaluhing pantig bawat taludtod. Ang awit ay may lalabindalawahing pantig.",
         "medium", "Anyo ng panitikan"),
        ("Ang 'Biag ni Lam-ang' ay epiko ng mga:", "Tagalog", "Ilokano", "Bisaya", "Bikolano", "B",
         "B ang tama: ang 'Biag ni Lam-ang' ay epikong Ilokano.", "easy", "Panitikang rehiyonal"),
        ("Tulang romansa na may lalabindalawahing pantig bawat taludtod at inaawit nang mabagal:", "korido", "awit",
         "haiku", "tanaga", "B",
         "B ang tama: ang awit ay may 12 pantig at mabagal ang himig. Ang korido ay 8 pantig, ang tanaga ay 7 pantig, at "
         "ang haiku ay 5-7-5.", "medium", "Anyo ng panitikan"),
        ("Sino ang may-akda ng nobelang 'Banaag at Sikat'?", "Lope K. Santos", "Valeriano Hernandez Peña",
         "Severino Reyes", "Jose Corazon de Jesus", "A",
         "A ang tama: si Lope K. Santos ang sumulat ng 'Banaag at Sikat' (1906).", "medium", "Mga akda at may-akda"),
    ],
}
