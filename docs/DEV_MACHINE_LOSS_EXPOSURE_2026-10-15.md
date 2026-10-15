# Exposition à la perte totale du poste de développement

Audit du 15 octobre 2026.

## Conclusion

Si le poste disparaissait maintenant, les services hébergés sur BODEFM,
PythonAnywhere, LWS, Meta et GitHub ne seraient pas physiquement détruits avec
l'ordinateur. En revanche, la continuité de développement subirait une perte
**élevée à critique** parce que les sauvegardes actuelles ne couvrent pas encore
les données, secrets et travaux locaux les plus récents.

Évaluation qualitative :

- impact immédiat sur les productions distantes : faible à modéré, sous réserve
  de conserver les accès ;
- perte de l'état local de Mining 360 : critique ;
- perte des credentials et configurations locales : critique ;
- perte Marketing Digital et mémoire MBA récents : élevée ;
- perte de connaissance : modérée, car une part importante de la documentation
  est maintenant poussée sur GitHub.

## Mesures observées

| Élément | État | Exposition |
| --- | --- | --- |
| Dossier MBA complet | 29 960 fichiers, 37,53 Gio, hors arborescence OneDrive | volume local important ; doublons et fichiers reconstructibles inclus |
| Base Mining 360 `db.sqlite3` | 13 893 255 168 octets | aucune sauvegarde externe actuelle vérifiée |
| WAL SQLite actif | 5 622 782 392 octets | une copie simple du seul fichier principal serait incomplète |
| SHM SQLite | 10 944 512 octets | composant de l'état actif local |
| Écarts Git Mining 360 | 1 215 entrées : 121 modifiées, 995 supprimées, 99 non suivies | les suppressions sont récupérables depuis Git ; les fichiers locaux modifiés/non suivis ne le sont pas tous |
| Fichiers locaux Mining 360 existants hors commit | 224 entrées, environ 0,138 Gio | code, documentation et ressources récentes à réconcilier |
| Exports Mining 360 | 800 fichiers, environ 761,76 Mio | ignorés par Git ; perte possible des livrables et preuves |
| Archives de continuité locales | environ 2 241,84 Mio | inutiles si le même disque est détruit |
| Marketing Digital | 9 fichiers, dépôt local `a1aa82b`, aucun remote | projet source perdu ; les données visibles dans Meta resteraient accessibles si le compte l'est |
| Mémoire et archives MBA hors dépôt | version actuelle et trois archives EMBA locales | anciennes copies OneDrive présentes, mais couverture actuelle non vérifiée |
| Secrets connus | sept emplacements locaux confirmés, hors OneDrive canonique | récupération ou rotation nécessaire si aucun coffre externe n'existe |

## Ce qui est déjà récupérable hors du poste

- Mining 360 : dépôt GitHub synchronisé au commit `7189057` au moment de l'audit ;
- Mayite : branche distante synchronisée au commit `d0191ec` ;
- DSTV : branche distante synchronisée au commit `709b277` ;
- Pacdigitale : branche distante synchronisée au commit `04569ee` ;
- productions et tests distants : BODEFM, PythonAnywhere, LWS et Meta restent des
  systèmes indépendants du poste ; leur reprise dépend des accès et de leurs
  propres sauvegardes ;
- OneDrive contient des sauvegardes historiques, notamment Mining 360 du 18 au
  28 septembre, un dump Mayite du 21 août et d'anciens documents MBA. Ces copies
  ne couvrent pas les changements les plus récents et ne constituent pas une
  restauration actuelle vérifiée.

## Pertes par projet

| Projet | Ce qui survivrait | Perte probable |
| --- | --- | --- |
| Mining 360 | code/documentation poussés, BODEFM | base SQLite active, WAL, exports, 224 entrées locales existantes non commitées, environnements et secrets courants |
| MiningProd | applications et bases sur BODEFM | accès locaux, outils de transfert et futur environnement local ; pas encore de clone local à perdre |
| Mayite | code GitHub et production PythonAnywhere | base MySQL locale, médias locaux, secrets ; ancien dump OneDrive seulement |
| DSTV | code GitHub et production PythonAnywhere | base MySQL locale, médias locaux et secrets ; aucun backup DB courant vérifié |
| Pacdigitale | thème GitHub et site LWS | base/configuration locale, `wp-config.php` et éléments non récupérables si LWS devient aussi inaccessible |
| Marketing Digital | résultats présents dans le compte Meta, résumé central GitHub | neuf fichiers sources et dépôt local complet, faute de remote |
| Mémoire MBA | quelques anciennes copies OneDrive et références centrales | version de validation actuelle, archives de cours et analyses locales non sauvegardées récemment hors poste |

## Priorités pour ramener le risque à un niveau acceptable

1. Produire une sauvegarde SQLite cohérente par l'API de backup, la valider avec
   `PRAGMA quick_check`, la chiffrer et la copier hors du poste.
2. Réconcilier les 224 entrées Mining 360 existantes, puis pousser les commits
   fonctionnels validés sans publier secrets, bases ou archives.
3. Configurer un remote privé pour Marketing Digital et y pousser `a1aa82b`.
4. Copier les livrables MBA actuels et leurs sources dans un espace externe
   chiffré et vérifier leur ouverture.
5. Produire des dumps MySQL cohérents de Mayite et DSTV, plus export WordPress et
   médias Pacdigitale, puis tester leur restauration.
6. Déplacer les secrets vers un coffre approuvé ou une archive AES-256 avec mot
   de passe conservé séparément ; vérifier que la clé de chiffrement Mining 360
   est récupérable.
7. Copier les archives de continuité vers au moins un support physiquement
   distinct et effectuer une restauration à blanc.

## Critère de sortie

Le risque ne pourra être qualifié de maîtrisé qu'après une restauration testée
des bases, sources, médias et secrets depuis un emplacement qui ne dépend pas de
ce poste.
