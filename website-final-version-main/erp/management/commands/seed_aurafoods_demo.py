from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from erp.models import (
    CashBankAccount, Company, CustomerDistributor, DailyProductionLog, PackagingBOM, PackagingBOMLine, Product,
    PurchaseRequirement, Recipe, RecipeIngredient, Supplier,
    ScheduledTaskConfig, SupplierPriceAgreement, SupplierTerm, UnitOfMeasure, Warehouse,
)


class Command(BaseCommand):
    help = "Seed minimal AuraFoods master data for local demos and UAT smoke testing."

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(is_superuser=True).first()
        kg, _ = UnitOfMeasure.objects.get_or_create(code="KG", defaults={"name": "Kilogram"})
        pcs, _ = UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Pieces", "unit_type": "count"})
        Warehouse.objects.get_or_create(code="MAIN", defaults={"name": "Main Warehouse", "created_by": user})
        Supplier.objects.get_or_create(code="SUP-DEMO", defaults={"name": "Demo Spice Supplier", "payment_terms_days": 15, "created_by": user})
        CashBankAccount.objects.get_or_create(code="CASH", defaults={"name": "Cash Counter", "balance": Decimal("0.00"), "created_by": user})
        raw, _ = Product.objects.get_or_create(
            code="RAW-TURMERIC",
            defaults={"name": "Raw Turmeric", "product_type": Product.ProductType.RAW, "base_unit": kg, "created_by": user},
        )
        powder, _ = Product.objects.get_or_create(
            code="PWD-TURMERIC",
            defaults={"name": "Turmeric Powder", "product_type": Product.ProductType.POWDER, "base_unit": kg, "created_by": user},
        )
        sku, _ = Product.objects.get_or_create(
            code="SKU-TURMERIC-100G",
            defaults={
                "name": "Turmeric Powder 100g",
                "product_type": Product.ProductType.FINISHED,
                "base_unit": pcs,
                "grammage": Decimal("0.100"),
                "shelf_life_days": 180,
                "created_by": user,
            },
        )
        pouch, _ = Product.objects.get_or_create(
            code="PACK-POUCH-100G",
            defaults={"name": "100g Printed Pouch", "product_type": Product.ProductType.PACKAGING, "base_unit": pcs, "created_by": user},
        )
        bom, _ = PackagingBOM.objects.get_or_create(
            finished_product=sku,
            version=1,
            defaults={"powder_product": powder, "powder_quantity_per_unit": Decimal("0.100000"), "created_by": user},
        )
        PackagingBOMLine.objects.get_or_create(bom=bom, packaging_product=pouch, defaults={"quantity_per_unit": Decimal("1.000000")})
        # Company profile
        wh_main = Warehouse.objects.filter(code="MAIN").first()
        co, _ = Company.objects.get_or_create(
            name="AuraFoods",
            defaults={
                "legal_name": "AuraFoods Spices (Pvt) Ltd",
                "default_currency": "PKR",
                "city": "Karachi",
                "country": "Pakistan",
                "financial_year_start_month": 7,
                "near_expiry_threshold_days": 30,
                "default_warehouse": wh_main,
                "po_prefix": "PO", "grn_prefix": "GRN", "inv_prefix": "INV",
                "pay_prefix": "PAY", "adv_prefix": "ADV",
                "dn_prefix": "DN", "cn_prefix": "CN",
                "prod_prefix": "PROD", "pack_prefix": "PACK", "adj_prefix": "ADJ",
            }
        )

        # Supplier terms for demo supplier
        sup_demo = Supplier.objects.filter(code="SUP-DEMO").first()
        if sup_demo:
            SupplierTerm.objects.get_or_create(
                supplier=sup_demo,
                defaults={
                    "payment_mode": "Bank Transfer",
                    "credit_days": 15,
                    "advance_required": True,
                    "shortage_tolerance_pct": Decimal("2.000"),
                    "replacement_policy": "Rejected quantity replaced within 3 days.",
                }
            )

        # Additional raw spices
        red_chili, _ = Product.objects.get_or_create(
            code="RAW-REDCHILI",
            defaults={"name": "Raw Red Chili", "product_type": "raw", "base_unit": kg,
                      "grade": "Premium", "origin": "Pakistan",
                      "expected_grinding_yield_pct": Decimal("82.000"),
                      "minimum_stock": Decimal("500"), "reorder_level": Decimal("200"),
                      "created_by": user},
        )
        coriander, _ = Product.objects.get_or_create(
            code="RAW-CORIANDER",
            defaults={"name": "Raw Coriander", "product_type": "raw", "base_unit": kg,
                      "grade": "A", "origin": "Pakistan",
                      "expected_grinding_yield_pct": Decimal("85.000"),
                      "minimum_stock": Decimal("300"), "reorder_level": Decimal("150"),
                      "created_by": user},
        )

        # Powder products for new raws
        pwd_chili, _ = Product.objects.get_or_create(
            code="PWD-REDCHILI",
            defaults={"name": "Red Chili Powder", "product_type": "powder", "base_unit": kg,
                      "linked_raw_spice": red_chili, "moisture_loss_allowance_pct": Decimal("3.000"),
                      "created_by": user},
        )
        pwd_coriander, _ = Product.objects.get_or_create(
            code="PWD-CORIANDER",
            defaults={"name": "Coriander Powder", "product_type": "powder", "base_unit": kg,
                      "linked_raw_spice": coriander, "moisture_loss_allowance_pct": Decimal("2.000"),
                      "created_by": user},
        )

        # Finished SKUs for new powders
        sku_chili, _ = Product.objects.get_or_create(
            code="SKU-REDCHILI-100G",
            defaults={"name": "Red Chili Powder 100g", "product_type": "finished",
                      "base_unit": pcs, "grammage": Decimal("0.100"),
                      "pack_type": "pouch", "shelf_life_days": 365,
                      "carton_quantity": 48, "label_version": "v1",
                      "created_by": user},
        )
        sku_cor, _ = Product.objects.get_or_create(
            code="SKU-CORIANDER-100G",
            defaults={"name": "Coriander Powder 100g", "product_type": "finished",
                      "base_unit": pcs, "grammage": Decimal("0.100"),
                      "pack_type": "pouch", "shelf_life_days": 365,
                      "carton_quantity": 48, "label_version": "v1",
                      "created_by": user},
        )

        # BOMs for new SKUs
        bom_chili, _ = PackagingBOM.objects.get_or_create(
            finished_product=sku_chili, version=1,
            defaults={"powder_product": pwd_chili, "powder_quantity_per_unit": Decimal("0.100000"),
                      "packing_wastage_pct": Decimal("1.000"), "created_by": user},
        )
        PackagingBOMLine.objects.get_or_create(
            bom=bom_chili, packaging_product=pouch, defaults={"quantity_per_unit": Decimal("1.000000")}
        )
        bom_cor, _ = PackagingBOM.objects.get_or_create(
            finished_product=sku_cor, version=1,
            defaults={"powder_product": pwd_coriander, "powder_quantity_per_unit": Decimal("0.100000"),
                      "packing_wastage_pct": Decimal("1.000"), "created_by": user},
        )
        PackagingBOMLine.objects.get_or_create(
            bom=bom_cor, packaging_product=pouch, defaults={"quantity_per_unit": Decimal("1.000000")}
        )

        # Demo recipe (Garam Masala)
        garam_fin, _ = Product.objects.get_or_create(
            code="SKU-GARAMMASALA-100G",
            defaults={"name": "Garam Masala 100g", "product_type": "finished",
                      "base_unit": pcs, "grammage": Decimal("0.100"),
                      "pack_type": "pouch", "shelf_life_days": 365, "created_by": user},
        )
        recipe, created = Recipe.objects.get_or_create(
            code="RCP-GARAM-001", version=1,
            defaults={
                "name": "Garam Masala Premium Formula",
                "finished_product": garam_fin,
                "standard_batch_size": Decimal("100"),
                "batch_unit": kg,
                "effective_date": "2026-01-01",
                "is_confidential": True,
                "status": "draft",
                "created_by": user,
            }
        )
        if created:
            RecipeIngredient.objects.create(recipe=recipe, ingredient=pwd_chili, quantity=Decimal("30.000"), percentage=Decimal("30.000"), sequence=1)
            RecipeIngredient.objects.create(recipe=recipe, ingredient=pwd_coriander, quantity=Decimal("25.000"), percentage=Decimal("25.000"), sequence=2)

        # Demo purchase requirement
        PurchaseRequirement.objects.get_or_create(
            number="PR-DEMO-001",
            defaults={
                "product": red_chili,
                "required_quantity": Decimal("500"),
                "source": "low_stock",
                "purpose": "Red chili stock below reorder level — seasonal restocking",
                "status": "draft",
                "created_by": user,
            }
        )

        SupplierPriceAgreement.objects.get_or_create(
            agreement_number="RATE-DEMO-001",
            defaults={
                "supplier": sup_demo,
                "product": raw,
                "item_type": SupplierPriceAgreement.ItemType.RAW_SPICE,
                "agreed_rate": Decimal("175.0000"),
                "currency": "PKR",
                "unit": kg,
                "effective_date": timezone.localdate(),
                "expiry_date": timezone.localdate() + timezone.timedelta(days=90),
                "rate_type": SupplierPriceAgreement.RateType.NEGOTIATED,
                "tolerance_percentage": Decimal("2.000"),
                "status": SupplierPriceAgreement.Status.ACTIVE,
                "created_by": user,
                "approved_by": user,
                "approved_at": timezone.now() if user else None,
            },
        )
        CustomerDistributor.objects.get_or_create(
            code="DIST-DEMO-001",
            defaults={
                "business_name": "Demo Foods Distributor",
                "contact_person": "Demo Buyer",
                "customer_type": CustomerDistributor.CustomerType.DISTRIBUTOR,
                "phone": "+92-300-0000000",
                "city": "Karachi",
                "country": "Pakistan",
                "credit_limit": Decimal("100000.00"),
                "credit_days": 15,
                "sales_channel": CustomerDistributor.SalesChannel.DISTRIBUTOR,
                "created_by": user,
            },
        )
        if user:
            DailyProductionLog.objects.get_or_create(
                log_number="PLOG-DEMO-001",
                defaults={
                    "log_date": timezone.localdate(),
                    "shift": DailyProductionLog.Shift.GENERAL,
                    "supervisor": user,
                    "operator": "Demo Operator",
                    "raw_quantity_issued": Decimal("100.000"),
                    "powder_quantity_received": Decimal("82.000"),
                    "grinding_wastage_quantity": Decimal("18.000"),
                    "remarks": "Safe demo shift log; no stock posting effect.",
                    "created_by": user,
                },
            )
        for job_name, command_name, frequency in (
            ("refresh_expiry_statuses", "refresh_expiry_statuses", "Daily at 01:00"),
            ("refresh_overdue_supplier_invoices", "refresh_overdue_supplier_invoices", "Daily at 01:15"),
            ("run_scheduled_erp_maintenance", "run_scheduled_erp_maintenance", "Daily at 01:30"),
        ):
            ScheduledTaskConfig.objects.get_or_create(
                job_name=job_name,
                defaults={
                    "command_name": command_name,
                    "frequency_description": frequency,
                    "created_by": user,
                },
            )

        # ── Seed opening stock batches ───────────────────────────────────────
        from erp.services import post_opening_stock
        raw_opening_items = [
            (raw, wh_main, "OB-TRM-2026-001", Decimal("500"), Decimal("180")),
            (red_chili, wh_main, "OB-CHI-2026-001", Decimal("300"), Decimal("220")),
            (coriander, wh_main, "OB-COR-2026-001", Decimal("200"), Decimal("150")),
        ]
        for product, warehouse, batch_no, qty, cost in raw_opening_items:
            try:
                post_opening_stock(
                    product=product, warehouse=warehouse, batch_number=batch_no,
                    quantity=qty, unit_cost=cost, user=user,
                    remarks="Opening stock — system migration"
                )
            except Exception:
                pass  # Skip if already seeded

        self.stdout.write(self.style.SUCCESS(
            f"\nAuraFoods demo data seeded:"
            f"\n  Company: {co.name}"
            f"\n  Products: {raw.code}, {powder.code}, {red_chili.code}, {coriander.code}, {sku_chili.code}, {sku_cor.code}"
            f"\n  Recipe: {recipe.code} v{recipe.version}"
            f"\n  Purchase Requirement: PR-DEMO-001"
        ))
