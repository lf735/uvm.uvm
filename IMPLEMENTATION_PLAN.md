# UVM SV Transpiler Suite — Plan d'implémentation v2

Suite de scripts Python de transpilation de fichiers SystemVerilog (`.sv`) pour environnement UVM.
Ce document est le plan d'implémentation **approuvé** — il intègre toutes les décisions de conception.

---

## Décisions de conception retenues

| Question | Décision |
|---|---|
| Scope V1 | Factory macros + `uvm_field_*` + vérification `new()` |
| Mode de modification | **In-place avec backup** (`.sv.bak`) |
| Classes paramétrées | **Oui**, supportées (`_param_utils`) |
| Rapport | Option CLI `--report <file.json>` + résumé console activable par `--verbose` |
| Exécution | Chaque script est indépendant + orchestrateur `uvm_transpile.py` |
| Parser | **Bibliothèque `lark`** (grammaire SV partielle/structurelle) |
| Versions futures | V2 : construction et connexion automatique d'environnement UVM |

---

## Architecture du projet

```
uvm/
├── uvm_transpile.py              # Orchestrateur principal
├── scripts/
│   ├── factory_checker.py        # Script 1 : macros `uvm_*_utils`
│   ├── field_macro_adder.py      # Script 2 : macros `uvm_field_*`
│   └── constructor_checker.py   # Script 3 : vérification/ajout de new()
├── core/
│   ├── sv_parser.py              # Parser Lark : détection de classes, membres, macros
│   ├── sv_grammar.lark           # Grammaire Lark SV structurelle
│   ├── uvm_taxonomy.py           # Hiérarchie UVM, règles de classification
│   ├── file_io.py                # Lecture/écriture in-place avec backup
│   └── reporter.py               # Rapport JSON + sortie console
├── tests/
│   ├── fixtures/                 # Fichiers .sv de test (un par cas)
│   │   ├── component_no_macro.sv
│   │   ├── object_wrong_macro.sv
│   │   ├── parameterized_class.sv
│   │   ├── multi_class_file.sv
│   │   ├── no_constructor.sv
│   │   └── ...
│   ├── test_factory_checker.py
│   ├── test_field_macro_adder.py
│   └── test_constructor_checker.py
├── requirements.txt              # lark, pytest, colorama
└── README.md
```

---

## Module `core/sv_parser.py` — Parser Lark

### Rôle
Parser structurel des fichiers `.sv`. Il n'implémente **pas** la grammaire SV complète, mais une grammaire ciblée qui extrait :
- Les déclarations de classes (nom, paramètres, parent)
- Les macros backtick présentes dans le corps des classes
- Les déclarations de fonctions/tâches (dont `new`)
- Les déclarations de membres (variables) pour `uvm_field_*`

### Grammaire Lark (`sv_grammar.lark`) — éléments clés

```lark
// Déclaration de classe
class_decl  : "virtual"? "class" IDENT param_decl? extends_clause? ";"
            | "virtual"? "class" IDENT param_decl? extends_clause? "implements" type_list ";"
param_decl  : "#" "(" param_list ")"
extends_clause : "extends" scoped_type

// Référence de type scopée (ex: uvm_pkg::uvm_driver)
scoped_type : IDENT ("::" IDENT)* ("#" "(" type_list ")")?

// Corps de classe — parsé comme séquence d'items
class_item  : macro_invocation
            | function_decl
            | variable_decl
            | COMMENT
            | ...

// Macro backtick (factory, field, etc.)
macro_invocation : "`" IDENT ("(" macro_args ")")?

// Déclaration de fonction (dont new)
function_decl : "function" type_ref? IDENT "(" port_list? ")" ";"? body "endfunction"

// Déclaration de variable membre
variable_decl : type_ref IDENT array_dim? ("=" expr)? ";"
```

### Objets de sortie du parser

```python
@dataclass
class SVClass:
    name: str
    is_virtual: bool
    is_parameterized: bool
    parent: str | None          # Nom résolu du parent (ex: "uvm_driver")
    parent_params: list[str]    # Paramètres du parent
    start_line: int
    end_line: int
    macros: list[SVMacro]
    members: list[SVMember]
    constructor: SVFunction | None
    raw_lines: list[str]        # Lignes brutes pour modification

@dataclass
class SVMacro:
    name: str           # ex: "uvm_component_utils"
    args: list[str]     # ex: ["my_driver"]
    line: int

@dataclass
class SVMember:
    name: str
    sv_type: str        # ex: "int", "string", "my_seq_item"
    is_array: bool
    is_queue: bool
    is_enum: bool
    line: int

@dataclass
class SVFunction:
    name: str           # "new", "build_phase", etc.
    port_list: list[SVPort]
    has_super_call: bool
    line: int
```

---

## Script 1 : `factory_checker.py` — Macros de factory

### Règles de classification

| Famille parente | Exemples | Macro attendue |
|---|---|---|
| `uvm_component` (et dérivés) | `uvm_driver`, `uvm_monitor`, `uvm_agent`, `uvm_env`, `uvm_test`, `uvm_scoreboard`, `uvm_subscriber`, `uvm_sequencer` | `` `uvm_component_utils(ClassName) `` |
| `uvm_object` (et dérivés) | `uvm_object`, `uvm_transaction`, `uvm_sequence_item`, `uvm_sequence`, `uvm_reg`, `uvm_reg_block`, `uvm_reg_field`, `uvm_mem` | `` `uvm_object_utils(ClassName) `` |
| Paramétrée + composant | idem ci-dessus avec `#(...)` | `` `uvm_component_param_utils(ClassName) `` |
| Paramétrée + objet | idem ci-dessus avec `#(...)` | `` `uvm_object_param_utils(ClassName) `` |

### Algorithme

```
Pour chaque SVClass dans le fichier :
  1. Résoudre parent → uvm_component | uvm_object | INCONNU
  2. Déterminer si paramétrée → choisir la macro cible
  3. Chercher une macro factory existante dans class.macros
  4. Décision :
     - ABSENT        → injecter à la ligne (start_line + 1)
     - BON TYPE, BON NOM → rien à faire
     - BON TYPE, MAUVAIS NOM → corriger le nom de classe dans la macro
     - MAUVAIS TYPE   → remplacer la macro entière
     - BLOC _begin/end → conserver le bloc, corriger uniquement le type/nom si nécessaire
  5. Si parent INCONNU → warning dans le rapport, ne pas modifier
```

### Cas particulier : bloc `_utils_begin/end`

Si une macro `_utils_begin` est présente, ne **pas** la remplacer par `_utils`. Corriger uniquement :
- Le préfixe (`component` ↔ `object`)
- Le nom de classe si erroné

---

## Script 2 : `field_macro_adder.py` — Macros `uvm_field_*`

### Prérequis
Ce script **requiert** que `factory_checker.py` ait déjà été exécuté (le bloc `_utils_begin/end` doit exister).
S'il n'existe pas encore, le script crée d'abord un bloc `_utils_begin/end` puis injecte les champs.

### Table de mapping type SV → macro `uvm_field_*`

| Type SV | Macro `uvm_field_*` |
|---|---|
| `int`, `integer`, `longint`, `shortint`, `byte`, `bit`, `logic`, `reg` | `` `uvm_field_int(name, flag) `` |
| `string` | `` `uvm_field_string(name, flag) `` |
| `real`, `shortreal` | `` `uvm_field_real(name, flag) `` |
| Enum (détecté par `typedef enum`) | `` `uvm_field_enum(type, name, flag) `` |
| Classe dérivée `uvm_object` | `` `uvm_field_object(name, flag) `` |
| Array statique `[N]` | `` `uvm_field_sarray_*(name, flag) `` |
| Array dynamique `[]` | `` `uvm_field_array_*(name, flag) `` |
| Queue `[$]` | `` `uvm_field_queue_*(name, flag) `` |
| AA `[type]` | `` `uvm_field_aa_*(name, flag) `` |

> [!NOTE]
> Le flag par défaut utilisé est `UVM_ALL_ON`. L'utilisateur pourra le surcharger via un fichier de configuration YAML futur.

### Algorithme

```
Pour chaque SVClass :
  1. Collecter tous les SVMember
  2. Pour chaque membre :
     a. Résoudre le type SV → macro cible (voir table)
     b. Vérifier si une macro `uvm_field_*` pour ce membre existe déjà dans le bloc
     c. Si ABSENT → ajouter dans le bloc _begin/end
     d. Si PRÉSENT → vérifier cohérence (nom, flag) — warning si incohérent
  3. Si aucun membre n'a de mapping connu → ne pas créer de bloc vide
```

> [!WARNING]
> Les membres **`local`** et **`protected`** sont inclus dans la détection mais marqués d'un warning dans le rapport (la field automation les expose potentiellement).

---

## Script 3 : `constructor_checker.py` — Vérification de `new()`

### Règles par famille

| Famille | Signature attendue | Appel `super` attendu |
|---|---|---|
| `uvm_component` | `function new(string name = "ClassName", uvm_component parent = null);` | `super.new(name, parent);` |
| `uvm_object` | `function new(string name = "ClassName");` | `super.new(name);` |

### Algorithme

```
Pour chaque SVClass :
  1. Chercher un SVFunction avec name == "new"
  2. Si ABSENT :
     → Générer et injecter le constructeur complet (signature + super.new)
        Position : juste après les macros factory
  3. Si PRÉSENT :
     a. Vérifier la signature (nombre et types de paramètres)
     b. Vérifier la valeur par défaut du name (= "ClassName")
     c. Vérifier la présence de super.new(...)
     d. Corriger si nécessaire (warning si super.new manquant)
```

---

## Orchestrateur `uvm_transpile.py`

```bash
# Exécuter tous les scripts sur un répertoire
python uvm_transpile.py --all path/to/sv/

# Exécuter un script spécifique
python uvm_transpile.py --factory path/to/sv/
python uvm_transpile.py --fields  path/to/sv/
python uvm_transpile.py --constructor path/to/sv/

# Options communes
--recursive           Parcourt les sous-répertoires
--no-backup           Désactive les backups (déconseillé)
--report out.json     Génère un rapport JSON
--verbose             Sortie console détaillée
--dry-run             Simule sans modifier les fichiers
```

### Ordre d'exécution (pipeline)

```
factory_checker  →  field_macro_adder  →  constructor_checker
```
L'ordre est important : `field_macro_adder` dépend du bloc `_begin/end` créé par `factory_checker`.

---

## Format du rapport JSON

```json
{
  "meta": {
    "timestamp": "2026-07-14T18:00:00",
    "mode": "fix",
    "scripts_run": ["factory_checker", "field_macro_adder", "constructor_checker"]
  },
  "summary": {
    "files_scanned": 12,
    "files_modified": 4,
    "classes_processed": 30,
    "actions": {
      "factory_macros_added": 5,
      "factory_macros_fixed": 2,
      "field_macros_added": 18,
      "constructors_added": 3,
      "constructors_fixed": 1
    },
    "warnings": 2
  },
  "files": [
    {
      "path": "my_driver.sv",
      "classes": [
        {
          "name": "my_driver",
          "uvm_family": "uvm_component",
          "actions": [
            { "type": "FACTORY_ADDED", "macro": "`uvm_component_utils(my_driver)", "line": 3 },
            { "type": "FIELD_ADDED",   "macro": "`uvm_field_int(timeout, UVM_ALL_ON)", "line": 5 },
            { "type": "CONSTRUCTOR_ADDED", "line": 10 }
          ]
        }
      ]
    }
  ],
  "warnings": [
    {
      "file": "my_base.sv",
      "class": "my_base",
      "message": "Parent class 'base_pkg::base_class' unresolved. Class skipped."
    }
  ]
}
```

---

## Plan d'implémentation par phases

### Phase 0 — Setup (½ jour)
- [ ] Initialiser le projet Python (`requirements.txt` : `lark`, `pytest`, `colorama`)
- [ ] Créer la structure de répertoires
- [ ] Créer les fixtures `.sv` de test

### Phase 1 — Core Parser (1–2 jours)
- [ ] `core/sv_grammar.lark` : grammaire Lark structurelle SV
  - Déclarations de classes (simple, virtuelle, paramétrée)
  - Macros backtick
  - Fonctions/tâches (dont `new`)
  - Variables membres
  - Gestion des commentaires et directives préprocesseur (`` `ifdef ``, `` `include `` → skip)
- [ ] `core/sv_parser.py` : interface Python sur le parser Lark → retourne `list[SVClass]`
- [ ] `core/uvm_taxonomy.py` : table de classification + résolution d'héritage
- [ ] Tests unitaires du parser

### Phase 2 — Script 1 : `factory_checker.py` (1 jour)
- [ ] Logique de décision (absent / correct / incorrect / bloc begin/end)
- [ ] Injection et remplacement dans les lignes brutes
- [ ] CLI avec `argparse`
- [ ] Tests (tous les cas du tableau de décision)

### Phase 3 — Script 2 : `field_macro_adder.py` (1–2 jours)
- [ ] Résolution de type SV → macro `uvm_field_*`
- [ ] Détection des membres déjà couverts
- [ ] Création/mise à jour du bloc `_begin/end`
- [ ] Tests

### Phase 4 — Script 3 : `constructor_checker.py` (1 jour)
- [ ] Détection et génération de la signature `new()`
- [ ] Vérification de `super.new()`
- [ ] Tests

### Phase 5 — Outillage (½ jour)
- [ ] `core/file_io.py` : backup + écriture in-place
- [ ] `core/reporter.py` : JSON + console colorée (`colorama`)
- [ ] `uvm_transpile.py` : orchestrateur avec pipeline ordonné

### Phase 6 — Tests d'intégration (½ jour)
- [ ] Test end-to-end sur un répertoire de fixtures complet
- [ ] Vérification que les fichiers produits sont valides SV

---

## Hors scope (V2)

- Construction et connexion automatique d'environnement UVM (`uvm_agent`, `uvm_env`)
- Gestion des `typedef ... sequencer` automatiques
- Vérification des `uvm_config_db::set/get`

---

## Dépendances Python

```
lark>=1.2.0       # Parser
pytest>=8.0       # Tests
colorama>=0.4.6   # Sortie console colorée
```
