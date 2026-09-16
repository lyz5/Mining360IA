# Mining 360 - Audit des sources de reconciliation CA / Commandes

Date d'audit : 7 septembre 2026

## 1. Perimetre

L'objectif est de rapprocher trois realites distinctes sans les confondre :

1. les commandes et leurs lignes ;
2. les factures commerciales et leurs lignes ;
3. le chiffre d'affaires comptable de CA Combine.

`Customer Fleet & Revenue Planning Model` reste une source de donnees uniquement. Il ne doit pas etre publie comme nouveau rapport dans le catalogue Mining 360.

## 2. Sources confirmees

### CA comptable

- Modele metier : `Customer Fleet & Revenue Planning Model` / CA Combine.
- Source historique documentee : `NMBEPM.dbo.ana_f_ecriture_analytique`.
- Filtre historique documente : `feca_taf_code LIKE 'CA'` et `tps_code_annee > 2024`.
- Principe de montant documente : credit moins debit apres consolidation.
- Reference de piece historique : `feca_num_piece_ecriture_comptable`.
- Limite : une piece comptable peut representer une facture, un avoir, une FAE ou une autre ecriture. Le numero seul ne certifie pas une facture commerciale.

### Commandes

- Rapport : `Mine Logistics Report`.
- Workspace : `a378c518-bfc4-4cd7-a49d-ba40394db80f`.
- Report ID : `e195601b-b576-4f3e-abae-f60629e2dc62`.
- Semantic model ID : `9db59281-164a-4992-b0a2-0c51837d1579`.
- Pages fonctionnelles documentees : `Mining Parts Tracking` et `Order Details`.
- Statuts attendus : BackOrder, Delivered, Disponible, Overdue et Picking Ongoing.
- `VW_BACKORDERS_TRACKING` ne couvre que le sous-ensemble BackOrder CAT et ne peut pas servir de source exhaustive des commandes.

### Dictionnaire IRIUM

Le fichier `DICO_IRIUM_DESCRIPTION_CHAMPS.xlsx` confirme :

- `NEG_ENT` : entete de commande ;
- `NEG_LIG` : lignes de commande ;
- `NEG_FAC` : entete de facture client ;
- `NEG_LLF` : lignes de livraison et de facture Negoce ;
- `IE_SALES_ORDER_LINE_ITEMS` est alimente historiquement par `NEG_LIG` ;
- `IE_SALES_DELIVERY_INVOICE_LINKAGE` est alimente historiquement par `NEG_LLF` ;
- `IE_CUSTOMER_INVOICE_HEADERS` est alimente historiquement par `NEG_FAC`.

## 3. Grains candidats

Ces grains sont des candidats a tester sur les donnees reelles avant de creer une contrainte d'unicite.

| Objet | Grain candidat | Statut |
|---|---|---|
| Entete commande | societe + succursale + numero de commande | A valider |
| Ligne commande | societe + succursale + numero de commande + numero de ligne | A valider |
| Facture commerciale | societe + succursale emettrice + numero de facture | A valider |
| Liaison livraison/facture | societe + commande + ligne + livraison + facture, combinaison exacte a tester | Source identifiee dans `NEG_LLF` |
| Ecriture CA | identifiant technique de l'ecriture analytique | A confirmer |

La reference piece ne doit jamais devenir la cle primaire de la reconciliation.

## 4. Relations candidates NEG_LIG, NEG_LLF et NEG_FAC

`NEG_LLF` doit etre le pont central. Une jointure directe `NEG_LIG -> NEG_FAC` perdrait la granularite livraison/facture et risquerait de masquer les facturations partielles.

### Ligne commande vers liaison livraison/facture

Relation candidate a tester :

```text
NEG_LIG.nlig_soc     = NEG_LLF.nllf_soc
AND NEG_LIG.nlig_succ    = NEG_LLF.nllf_succ
AND NEG_LIG.nlig_numcde  = NEG_LLF.nllf_numcde
AND NEG_LIG.nlig_nolign  = NEG_LLF.nllf_nolign
```

La reference article `nlig_refp/nllf_refp`, le type de ligne et la ligne maitre doivent servir de controles supplementaires, pas etre ajoutes aveuglement a la cle avant un test de cardinalite.

### Liaison livraison/facture vers entete facture

Le dictionnaire confirme les champs suivants :

| NEG_LLF | Sens | Controle ou correspondance candidate NEG_FAC |
|---|---|---|
| `nllf_numfac` | numero de facture | `nfac_numfac` |
| `nllf_succfac` | succursale ayant emis la facture | `nfac_succ` |
| `nllf_servfac` | service ayant emis la facture | `nfac_serv` |
| `nllf_numcli` | numero client | `nfac_numcli`, controle de coherence |
| `nllf_soc` | code societe | `nfac_soc`, a confirmer pour les factures inter-societes |
| `nllf_numfacann` | facture d'annulation logique | traitement des annulations et avoirs a qualifier |

Relation candidate a tester :

```text
NEG_LLF.nllf_numfac  = NEG_FAC.nfac_numfac
AND NEG_LLF.nllf_succfac = NEG_FAC.nfac_succ
AND NEG_LLF.nllf_servfac = NEG_FAC.nfac_serv
AND NEG_LLF.nllf_soc = NEG_FAC.nfac_soc
AND contexte societe/client compatible
```

`NEG_LLF` contient aussi `nllf_numliv`, `nllf_qtecde`, `nllf_qtefac`, `nllf_qteliv`, `nllf_pxvteht`, `nllf_pxnredv`, `nllf_pxvtedv`, `nllf_pos` et `nllf_natop`. Ces champs permettent de controler les livraisons, quantites facturees, montants et natures d'operation au niveau du pont.

Le dictionnaire rend cette architecture probable, mais la cardinalite doit encore etre prouvee sur les donnees : plusieurs lignes `NEG_LLF` doivent pouvoir representer plusieurs livraisons ou factures pour une meme ligne `NEG_LIG` sans dupliquer les montants d'entete `NEG_FAC`.

## 5. Champs utiles confirmes

### Commande et ligne

- `nent_numcde`, `nent_numcli`, `nent_soc`, `nent_succ` ;
- `nlig_numcde`, `nlig_nolign`, `nlig_datecde` ;
- `nlig_numcli`, `nlig_soc`, `nlig_succ` ;
- `nlig_qtecde`, `nlig_qtefac`, `nlig_qteliv` ;
- `nlig_pxvteht`, `nlig_pxvtedv` ;
- `nlig_ref`, `nlig_typecde`, `nlig_typlig` ;
- `nlig_numfac`, `nlig_succfac`, `nlig_servfac`.

### Facture

- `nfac_numfac`, `nfac_numfacm` ;
- `nfac_datefac`, `nfac_numcli` ;
- `nfac_soc`, `nfac_succ`, `nfac_serv` ;
- `nfac_code` avec `D = debit` selon le dictionnaire ;
- `nfac_devise`, `nfac_pos`.

### Liaison livraison et facture

- `nllf_numcde`, `nllf_nolign`, `nllf_nolmait` ;
- `nllf_numliv`, `nllf_numfac`, `nllf_numfacann` ;
- `nllf_numcli`, `nllf_soc`, `nllf_succ` ;
- `nllf_succfac`, `nllf_servfac`, `nllf_succliv` ;
- `nllf_qtecde`, `nllf_qtefac`, `nllf_qteliv` ;
- `nllf_pxvteht`, `nllf_pxnredv`, `nllf_pxvtedv` ;
- `nllf_refp`, `nllf_pos`, `nllf_natop`, `nllf_natopet`.

### Montants d'entete a qualifier

- `neg_ent.nent_facht` : CA HT de la facture ;
- `neg_ent.nent_facttc` : CA TTC de la facture.

Le nom `NENT_FAC` n'existe pas comme objet exact dans le dictionnaire fourni. Il ne faut pas le confondre avec `nent_facht` ou `nent_facttc` sans exemple provenant de la source actuelle.

## 6. Regles anti-double comptage

La future reconciliation devra conserver des ponts explicites :

```text
Commande -> Ligne commande -> Ligne facture -> Facture commerciale -> Ecriture CA
```

Controles obligatoires :

- une ligne commande peut etre facturee plusieurs fois ;
- une facture peut couvrir plusieurs commandes et plusieurs lignes ;
- les avoirs doivent etre relies a leur facture ou a leur contexte commercial ;
- une FAE ne doit pas etre classee automatiquement comme facture commerciale ;
- les quantites commandees, livrees et facturees restent distinctes ;
- les montants commande, facture commerciale et CA comptable restent distincts ;
- les montants en devise d'origine et consolides ne doivent pas etre additionnes ensemble ;
- un rapprochement ambigu reste `A revoir`, jamais `Rapproche` par defaut.

## 7. Etat des acces techniques

| Controle | Resultat |
|---|---|
| Rapport `Mine Logistics Report` enregistre dans Mining 360 | Oui |
| Semantic model identifie | Oui |
| Lecture du schema par Power BI ExecuteQueries | Echec 401 `PowerBINotAuthorizedException` |
| Power Automate retenu pour `Mine Logistics Report` | `InspectData 3` uniquement |
| Configuration locale de `InspectData 3` | URL absente au 7 septembre 2026 ; echec controle et persiste |
| Lecture de `ChriffreAffaire` dans `Customer Fleet & Revenue Planning Model` | Operationnelle via Power BI ExecuteQueries |
| Metadonnees Orders/Invoice importees localement | Aucune trouvee |
| Connexion Snowflake | Hors architecture de synchronisation demandee ; aucune connexion utilisee |
| Formule exacte de `StatutGlobal` | Non accessible |
| Table complete alimentant `Mining Parts Tracking` | Non accessible |
| Source candidate des liaisons livraison/facture | `NEG_LLF` / `IE_SALES_DELIVERY_INVOICE_LINKAGE` identifiee |
| Cardinalite et historique complet des facturations partielles | A tester sur les donnees reelles |

## 8. Contrats de source proposes

Avant l'interface, chaque adaptateur devra retourner un contrat stable :

- `AccountingRevenueSource`: ecritures CA, type d'ecriture, piece, client, dates, devise, debit, credit, montant consolide ;
- `SalesOrderSource`: entetes et lignes, quantites, montants, statut officiel et historique ;
- `CommercialInvoiceSource`: entetes et lignes de facture, references commande/ligne, quantites, montants, avoirs ;
- `ReconciliationRuleSet`: cles autorisees, tolerances, priorites, dates, devises et exclusions.

Les adaptateurs seront en lecture seule. Les resultats, exceptions, decisions manuelles et versions de regles seront persistes dans la base Mining 360.

## 9. Conditions necessaires avant certification du moteur

Il reste a obtenir :

1. la table ou requete exacte qui alimente les cinq statuts de `Mining Parts Tracking` ;
2. la formule actuelle complete de `StatutGlobal` ;
3. les mesures officielles du montant commande et du montant restant ;
4. l'emplacement et la definition exacte de `NENT_FAC` ;
5. la confirmation que `IE_SALES_DELIVERY_INVOICE_LINKAGE` conserve l'historique exhaustif, y compris les facturations partielles et annulations ;
6. quatre cas reels anonymisables : facture simple, commande partiellement facturee, commande non facturee et avoir ;
7. la regle de jointure certifiee entre facture commerciale et ecriture CA ;
8. les regles de devise, dates, annulations, FAE et tolerance de montant.

## 10. Decision de faisabilite

Le socle persistant et le moteur deterministe sont implementes, mais les liens ligne a ligne ne sont pas encore certifies sur les donnees reelles. Les rapprochements restent donc explicitement `NOT_CERTIFIED` afin de ne pas presenter de faux positifs sur les facturations partielles, les avoirs ou les FAE.

La prochaine etape operationnelle est de configurer l'URL securisee de `InspectData 3`, charger les buffers, puis tester les quatre cas reels. L'interface `Invoice Tracking Detailed` affiche les statuts reels et les limites ; elle ne transforme pas les rapprochements en verite certifiee.

## 11. Socle backend implemente

Migration appliquee : `reports.0123_reconciliation_ca_orders_foundation`.

Tables persistantes creees dans Mining 360 :

- `rec_source_snapshot` ;
- `rec_order_line` ;
- `rec_delivery_invoice_link` ;
- `rec_invoice_header` ;
- `rec_accounting_entry` ;
- `rec_run` ;
- `rec_match` ;
- `rec_match_accounting_entry`.

Le moteur `RevenueOrderReconciliationService` applique uniquement des cles exactes et conserve plusieurs ecritures CA pour une meme facture. Il distingue :

- rapprochement exact ;
- facturation partielle ;
- annulation logique ;
- commande absente ou ambigue ;
- facture absente ou ambigue ;
- CA comptable absent.

Le moteur reste marque `NOT_CERTIFIED` dans chaque resume d'execution jusqu'a validation sur les donnees reelles. Aucune publication Business Review n'est activee.

Commande d'execution disponible :

```text
python manage.py run_ca_orders_reconciliation
```

Commande de synchronisation complete des modeles semantiques vers les buffers Mining 360 :

```text
python manage.py sync_reconciliation_buffers
```

La synchronisation utilise :

- `Mine Logistics Report` via `InspectData 3` pour commandes, liaisons livraison/facture et entetes facture ;
- `Customer Fleet & Revenue Planning Model` pour `ChriffreAffaire` ;
- la base Mining 360 pour les snapshots, les buffers, les executions et les resultats.

L'interface est disponible sur `/invoice-tracking/` avec progression AJAX, filtres, pagination et export CSV.

La commande refuse une execution partielle lorsqu'un snapshot `Ready` manque. Le lancement reel du 7 septembre a ete arrete proprement avant import, car l'URL `InspectData 3` n'etait pas encore configuree. Cet echec est conserve dans `ReconciliationBufferSyncRun`; aucun enregistrement fictif ou partiel n'a ete cree.

Tests automatises passes :

- facturation partielle sur deux factures ;
- commande completement facturee en plusieurs factures ;
- plusieurs lignes comptables sans double comptage de facture ;
- annulation logique ;
- facture absente ;
- idempotence d'une execution sur les memes snapshots et la meme version de regles.
