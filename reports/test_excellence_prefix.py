from types import SimpleNamespace
from django.http import QueryDict
from django.test import SimpleTestCase
from .excellence_filter_values import option_filters, prefix_clause
from .homepage_availability_service import HomepageAvailabilityService, HomepageAvailabilityError
from .homepage_fuel_service import HomepageFuelService
from .homepage_connectivity_service import HomepageConnectivityService


class ExcellencePrefixTests(SimpleTestCase):
    def services(self):
        for cls in (HomepageAvailabilityService, HomepageFuelService, HomepageConnectivityService):
            service = cls.__new__(cls)
            service.config = SimpleNamespace(default_period='ytd',default_breakdown='overall',equipment_page_size=25)
            service.filter_mappings = {'serial_number': {'powerbi_table_name':'EquipmentList_MiningProd','powerbi_column_name':'SN'}}
            yield service

    def test_scalar_and_multi_prefixes_are_uppercase_and_validated(self):
        for service in self.services():
            self.assertEqual(service.request_from_params({'prefix':'xdt'}).filters['prefix'],'XDT')
            self.assertEqual(service.request_from_params(QueryDict('prefix=xdt&prefix=spd')).filters['prefix'],['XDT','SPD'])
            for invalid in ('XDT02044','XD','*','X D'):
                with self.assertRaises(HomepageAvailabilityError):service.request_from_params({'prefix':invalid})

    def test_prefix_matches_serial_starts_not_equipment_names(self):
        clause = prefix_clause("'EquipmentList_MiningProd'[SN]", ['XDT','7W8'])
        self.assertIn('LEFT(UPPER(TRIM(',clause)
        self.assertIn('IN {"XDT", "7W8"}',clause)
        for service in self.services():
            method = getattr(service,'_filter_clauses',None) or service._clauses
            self.assertIn(clause,method({'prefix':['XDT','7W8']}))

    def test_prefix_options_do_not_discard_site_authorization_or_model(self):
        scope={'minesite':['SNIM-Guelb']}
        merged={**scope,'model':['789'],'prefix':['XDT'],'equipment':['DT395']}
        self.assertEqual(option_filters(merged,scope,'prefix'),{**scope,'model':['789']})
        self.assertEqual(option_filters(merged,scope,'equipment')['prefix'],['XDT'])
        for service in self.services():
            with self.assertRaises(HomepageAvailabilityError):
                service._merge_filters(scope,{'minesite':['Forbidden'],'prefix':['XDT']})

    def test_connectivity_prefix_options_keep_official_counts_and_focus(self):
        service=HomepageConnectivityService.__new__(HomepageConnectivityService)
        request=service.request_from_params({'prefix':['XDT','SPD']})
        dax=service.build_dax(request,{'minesite':['SNIM-Guelb'],'prefix':['XDT','SPD']},{'minesite':['SNIM-Guelb']})
        self.assertIn('"option_prefix"',dax)
        self.assertIn('[Nb Equip]',dax)
        self.assertEqual(dax.count('[Focus]'),6)
        self.assertEqual(dax.count('TREATAS({"SNIM-Guelb"}'),6)
