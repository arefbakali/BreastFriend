"""Outils texte partagés par l'ingestion et la recherche."""
import re
import unicodedata

_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# Stopwords français (minuscules, sans accents) pour la requête BM25.
FRENCH_STOPWORDS = frozenset("""
a au aux avec ce ces cet cette dans de des du elle elles en et eux il ils je la le les leur leurs lui ma
mais me meme mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi
ton tu un une vos votre vous c d j l m n s t y est sont ete etre avoir ai as avons avez ont suis es
etes fait faire plus tres tout tous toute toutes si comme quand ceci cela ca quoi dont peut peuvent
alors aussi autre autres bien car chez donc encore entre ici jusqu lorsque puis sans selon sous
quel quelle quels quelles comment pourquoi combien est-ce qu'est-ce faut dois doit
dis dire explique expliquer parle parler veux voudrais aimerais savoir peux pouvez merci svp stp
donne donner donnez donnes montre moi toi lui chose choses truc info infos information informations
""".split())


def count_tokens(text):
    """Estimation du nombre de tokens (mots + ponctuation).

    Les tokenizers sous-mots (bge-m3, GPT) produisent en moyenne ~1,3 token par mot
    français : on applique ce facteur pour que CHUNK_SIZE_TOKENS reste réaliste
    sans dépendre d'un tokenizer précis.
    """
    return int(len(_TOKEN.findall(text)) * 1.3) + 1


def fold(text):
    """Minuscules sans accents (comparaisons, requêtes)."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_query(text):
    """Nettoyage léger de la question avant embedding (on garde la casse et les accents)."""
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"[\u0000-\u001f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:2000]


def keyword_terms(text, max_terms=24):
    terms, seen = [], set()
    for w in re.findall(r"[a-z0-9]+", fold(text)):
        if len(w) < 2 or w in FRENCH_STOPWORDS or w in seen:
            continue
        seen.add(w)
        terms.append(w)
    return terms[:max_terms]


def term_coverage(query, text):
    """Part des termes de la requête présents dans le texte (préfixe de 5 lettres : pluriels, accords)."""
    terms = keyword_terms(query)
    if not terms:
        return 0.0
    words = set(re.findall(r"[a-z0-9]+", fold(text)))
    stems = {w[:5] for w in words}
    hit = sum(1 for t in terms if t in words or (len(t) >= 5 and t[:5] in stems))
    return hit / len(terms)
