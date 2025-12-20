from password_strength import PasswordStats

text = "rkjgnakuvrnakhvkjdaaa >//////////////////< I log on fedi and there's so many boosts and reactions of my post saying \"React and boost if I'm cute\" >////////////<"


for k in text.split(" "):
    password = PasswordStats(k)
    print(k, password.strength())
    if password.strength() > 0.7:
        print(password.alphabet)
        print(password.char_categories)
        print(password.combinations)
        print(password.entropy_bits)
        print(password.entropy_density)
        print(password.letters)
        print(password.letters_lowercase)
        print(password.letters_uppercase)
        print(password.numbers)
        print(password.repeated_patterns_length)
        print(password.sequences_length)
        print(password.special_characters)
        print(password.weakness_factor)
        print(password.count)
        print(password.count_except)
