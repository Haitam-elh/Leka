"""What a request's words ask for (LEKA-371): the words a retrieval searches.

A request comes as a sentence — "pourquoi la facturation est-elle lente ?",
"who owns checkout?" — in French or English, about systems named in
English. A search for every word of it finds nothing; a search for any of
them, ranked by how many a thing holds, finds what it is about — once the
words that say nothing are left out, and the words a company's systems are
named in are added to the asker's.

    words()     the words that say something, folded: "facturation", "lente"
    expanded()  the same, and what they mean in the other language, or are
                also called: "billing", "invoice", "slow", "latency"
    content()   a tsquery for the records' own text (ingestion's index):
                the words as written — accents kept, the index keeps them
                — folded, and expanded

Pure, and deliberately small: a vocabulary of the words an IT question is
made of, not a dictionary. It is what retrieval reads without paying a
model; an embedding of the sentence (LEKA-372 and after) would come beside
it, never instead — it says why a thing was found, in words.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from leka.knowledge import fold

# Past this many, a sentence's words say nothing more — and the synonyms.
MAX_WORDS = 12
MAX_EXPANDED = 24
MAX_CONTENT = 32

# The words that say nothing of what is asked, in French and in English.
_SAY_NOTHING = """
    a ai ait alors apres as au aucun aussi autre aux avait avant avec
    avoir c ca car ce ceci cela celle celui ces cet cette chez comme
    comment d dans de des depuis deja doit donc dont du elle elles en
    encore entre est et etaient etait ete etre eu fait faire fais faut
    il ils j je l la le les leur leurs lui m ma mais me meme mes moi
    moins mon n ne ni nos notre nous on ont ou oui par parce pas peu
    peut plus pour pourquoi puis qu quand que quel quelle quelles quels
    qui quoi s sa sans se ses si son sont sous suis sur t ta te tes toi
    ton tous tout toute toutes tres trop tu un une vers voici voila vont
    vos votre vous y
    about after again all also am an and any are as at be been before
    being but by can could did do does doing down for from had has have
    having he her here him his how i if in into is it its just me more
    most my no not now of off on once only or other our out over own
    same she should so some still such than that the their them then
    there these they this those through to too under until up very was
    we were what when where which while who whom why will with would yet
    you your
"""
STOPWORDS = frozenset(_SAY_NOTHING.split())

# What the same thing is called, in either language, or otherwise: an
# asker's word and the words a company's systems are named in. Folded.
CONCEPTS: tuple[tuple[str, ...], ...] = (
    ("lent", "lente", "lenteur", "slow", "latence", "latency", "performance", "p95", "p99"),
    ("panne", "down", "outage", "indisponible", "unavailable", "incident"),
    ("erreur", "error", "echec", "failure", "failed", "exception", "bug"),
    ("deploiement", "deploye", "deploy", "deployment", "livraison", "release"),
    ("changement", "change", "modification"),
    ("facturation", "facture", "billing", "invoice", "invoicing"),
    ("paiement", "payment", "pay"),
    ("bdd", "database", "db"),
    ("equipe", "team", "squad"),
    ("proprietaire", "responsable", "owner", "owns", "maintainer"),
    ("documentation", "doc", "docs", "runbook", "procedure", "wiki"),
    ("reprise", "recovery", "restart", "relance", "retry"),
    ("securite", "security", "vulnerabilite", "vulnerability"),
    ("serveur", "server", "instance", "machine", "host"),
    ("utilisateur", "user", "client", "customer"),
    ("connexion", "login", "authentification", "authentication", "auth"),
    ("stockage", "storage", "bucket"),
    ("reseau", "network", "vpc"),
    ("dependance", "dependency", "depend", "depends"),
    ("sauvegarde", "backup"),
    ("alerte", "alert", "monitoring", "supervision"),
    ("commande", "order"),
    ("expedition", "shipping", "livraisons"),
    ("stock", "inventory", "inventaire"),
)
_MEANS: dict[str, tuple[str, ...]] = {word: group for group in CONCEPTS for word in group}
# A word as written, accents kept: what the records' index holds.
_WRITTEN = re.compile(r"[^\W_]+")


def words(text: str | None) -> list[str]:
    """The words of `text` that say something, folded, each once, in order:
    "Pourquoi Billing API est lent ?" → billing, api, lent."""
    found = [
        word
        for word in fold(text or "").split()
        if word not in STOPWORDS and (len(word) > 1 or word.isdigit())
    ]
    return list(dict.fromkeys(found))[:MAX_WORDS]


def expanded(said: Iterable[str]) -> list[str]:
    """The words, then what each also means: lent → slow, latency."""
    said = list(said)
    more = [other for word in said for other in _means(word) if other != word]
    return list(dict.fromkeys([*said, *more]))[:MAX_EXPANDED]


def content(text: str | None) -> str | None:
    """A tsquery for the records' own text: any of the words, each a
    prefix, as written and folded — "données" and "donnees" — and what
    they also mean. None when nothing says anything."""
    said = words(text)
    if not said:
        return None
    written = [
        word
        for word in _WRITTEN.findall((text or "").lower())
        if fold(word) in said and word != fold(word)
    ]
    kept = list(dict.fromkeys([*written, *expanded(said)]))[:MAX_CONTENT]
    return " | ".join(f"{word}:*" for word in kept)


def _means(word: str) -> tuple[str, ...]:
    """What a word also means — its plural or feminine read as it."""
    for form in (word, word.removesuffix("s"), word.removesuffix("es"), word.removesuffix("e")):
        if form in _MEANS:
            return _MEANS[form]
    return ()
