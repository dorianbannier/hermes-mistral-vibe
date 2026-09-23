# Hermes Mistral Vibe

Plugin communautaire **non officiel** qui ajoute le fournisseur `mistral-vibe` à
[Hermes Agent](https://github.com/NousResearch/hermes-agent). Il utilise l’API
Chat Completions de Mistral directement : Hermes conserve sa boucle agent, ses
outils et son interface.

> **Facturation :** voir un modèle dans `GET /v1/models` prouve seulement sa
> visibilité pour le compte. Cela ne garantit pas qu’il soit couvert par un quota
> Vibe. Mistral recommande le **pay-as-you-go (PAYG) pour l’automatisation API**.
> Vérifiez votre offre, vos limites et les conditions Mistral avant toute
> inférence réelle.

**English summary:** Unofficial community provider for direct Mistral Vibe access
from Hermes. Account-visible models are not proof of Vibe quota coverage; Mistral
recommends PAYG for API automation. Review billing and access terms before use.

## Fonctionnement

- connexion navigateur Mistral avec PKCE, stockée dans le pool Hermes dédié
  `mistral-vibe` ;
- alternative manuelle `MISTRAL_VIBE_API_KEY` ;
- découverte en lecture seule via `https://api.mistral.ai/v1/models` ;
- filtrage strict sur `capabilities.completion_chat: true` ;
- modèle de secours `mistral-vibe-cli-latest` ;
- aucune utilisation de `MISTRAL_API_KEY` et aucune substitution interne de
  modèle.

## Prérequis

- une version récente de Hermes Agent prenant en charge les plugins
  `kind: model-provider` ;
- l’interpréteur Python de l’installation Hermes, avec `httpx` et `openai` ;
- un domicile Hermes explicite. Le profil actif est normalement
  `${HERMES_HOME:-$HOME/.hermes}`.

Contrat Hermes :
<https://hermes-agent.nousresearch.com/docs/developer-guide/model-provider-plugin>

## Installation

Clonez le dépôt, puis indiquez explicitement le domicile du profil à modifier :

```sh
git clone https://github.com/dorianbannier/hermes-mistral-vibe.git
cd hermes-mistral-vibe
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
python3 install.py --home "$HERMES_HOME"
```

L’installateur utilise uniquement la bibliothèque standard Python. Il ne touche
qu’à :

```text
$HERMES_HOME/plugins/model-providers/mistral-vibe/
  __init__.py
  plugin.yaml
  vibe_provider.py
```

Il ne lit et ne modifie ni `config.yaml`, ni `auth.json`, ni `.env`. Une
installation existante est refusée par défaut.

### Mise à jour

`--update` remplace une installation qui ne contient que les trois fichiers gérés.
La présence d’un fichier inattendu provoque un refus :

```sh
python install.py --home "$HERMES_HOME" --update
```

`--force` supprime puis remplace **uniquement** le dossier du plugin, y compris ses
fichiers inattendus. N’utilisez cette option qu’après inspection et sauvegarde :

```sh
python install.py --home "$HERMES_HOME" --force
```

Rafraîchissez ou redémarrez Hermes Desktop après installation ou mise à jour afin
de recharger le code Python. Le script ne change jamais le fournisseur ni le
modèle configuré.

## Authentification

Connexion navigateur :

```sh
HERMES_HOME="$HERMES_HOME" hermes auth add mistral-vibe
# Machine sans navigateur :
HERMES_HOME="$HERMES_HOME" hermes auth add mistral-vibe --no-browser
HERMES_HOME="$HERMES_HOME" hermes auth status mistral-vibe
```

L’URL temporaire affichée est sensible. Le credential est enregistré par Hermes
dans le pool `mistral-vibe` de `auth.json` avec les protections fournies par
Hermes ; ce stockage local n’est pas présenté comme chiffré. La variable
`MISTRAL_VIBE_API_KEY` a priorité si elle est définie.

La sélection du fournisseur/modèle reste une action volontaire de l’utilisateur,
par exemple via `hermes model`. Ce dépôt et son installateur ne modifient pas
`config.yaml`.

## Tests hors ligne

```sh
python3 run_tests.py
```

La suite crée des `HOME` et `HERMES_HOME` jetables, bloque les connexions socket,
et remplace toutes les réponses HTTP par des fixtures. Elle couvre notamment
l’installation non destructive, la découverte Hermes, l’authentification PKCE,
le catalogue, les caches, le transport synchrone/asynchrone, le streaming et les
garde-fous de requête. Aucun compte ni secret réel n’est requis.

## Sécurité et limites

- Origines fixées à `https://console.mistral.ai` pour l’authentification et
  `https://api.mistral.ai/v1` pour le catalogue et l’inférence.
- Redirections, proxies hérités de l’environnement et retries internes du SDK
  sont désactivés. Hermes ou d’autres fournisseurs peuvent conserver leurs
  propres retries, routes ou coûts.
- Le client accepte seulement `mistral-vibe-cli-latest` ou un modèle chat du
  catalogue courant de la clé dédiée. Les erreurs remontent sans substitution
  interne.
- Le cache mémoire est séparé par fournisseur, domicile Hermes et empreinte non
  secrète de la clé. La clé brute n’est pas mise en cache.
- `auth status`, `whoami` ou `GET /models` ne prouvent ni la couverture tarifaire,
  ni le quota, ni le prix. Aucune inférence n’est lancée pour tester la couverture.
- Les endpoints Vibe et leurs conditions peuvent changer sans préavis. Ce plugin
  communautaire n’est affilié ni à Mistral AI ni à Nous Research.

## Déconnexion et désinstallation

```sh
HERMES_HOME="$HERMES_HOME" hermes auth logout mistral-vibe
rm -rf -- "$HERMES_HOME/plugins/model-providers/mistral-vibe"
```

La déconnexion efface le pool local, mais ne révoque pas nécessairement la clé
distante. Retirez aussi `MISTRAL_VIBE_API_KEY` de votre environnement et utilisez
les moyens fournis par Mistral pour toute révocation distante. La désinstallation
ne doit supprimer aucun autre fichier du domicile Hermes.

## Licence

MIT — voir [LICENSE](LICENSE).
