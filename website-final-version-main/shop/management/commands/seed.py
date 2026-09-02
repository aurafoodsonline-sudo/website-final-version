import os
from decimal import Decimal

from django.core.management.base import BaseCommand
from shop.models import BlogPost, Bundle, Category, DeliveryZone, FAQItem, Product, ProductVariant, Setting, SitePage, Testimonial, WhyItem
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Seed initial data'

    def handle(self, *args, **options):
        if not User.objects.exists():
            admin_password = os.environ.get('AURAFOODS_ADMIN_PASSWORD')
            if admin_password:
                User.objects.create_superuser('admin', 'admin@aurafoods.pk', admin_password)
                self.stdout.write('Created admin user')
            else:
                user = User.objects.create_user(
                    'admin',
                    'admin@aurafoods.pk',
                    password=None,
                    is_staff=True,
                    is_superuser=True,
                )
                user.set_unusable_password()
                user.save(update_fields=['password'])
                self.stdout.write('Created admin user with an unusable password. Set AURAFOODS_ADMIN_PASSWORD before seeding for local access.')

        if Setting.objects.count() == 0:
            settings_data = [
                ('site_name','Aura Foods'),
                ('site_tagline','Pure & Premium Organic Spices of Pakistan'),
                ('hero_title','Pure & Premium <em>Organic Spices</em>'),
                ('hero_subtitle','Freshly packed authentic spices from the fields of Sindh, delivered across Pakistan.'),
                ('hero_badge','Hand-sourced · Stone-ground · Freshly packed'),
                ('about_title','From Sindh Soil to Your Spice Rack'),
                ('about_content','We trace every spice back to the family farms of Kunri — the chili capital of Asia.'),
('phone','+92 335 2832967'),
                ('email','aurafoodsonline@gmail.com'),
                ('whatsapp','923352832967'),
                ('hero_image','/static/images/hero-spices.jpg'),
                ('story_image','/static/images/quality-story.jpg'),
                ('story_location','Kunri, Sindh'),
            ]
            for k,v in settings_data:
                Setting.objects.create(key=k, value=v)
            self.stdout.write('Settings seeded')

        if Category.objects.count() == 0:
            cats = ["Red Chili Powder","Turmeric Powder","Coriander Powder","Garam Masala","Premium Blends","Salt Range"]
            for i, c in enumerate(cats):
                Category.objects.create(name=c, image=f'/static/images/{c.lower().replace(" ","-")}.jpg', sort_order=i)
            self.stdout.write('Categories seeded')

        if Product.objects.count() == 0:
            cat_map = {c.name: c.id for c in Category.objects.all()}
            prods = [
                ("kunri-red-chili","Kunri Red Chili Powder (Pisi Lal Mirch)","Hand-picked from Sindh",199,249,"200g","/static/uploads/product01.jpeg","Red Chili Powder","Pure red chili powder sourced from Kunri, Sindh — the chili capital of Asia. Vibrant red color, rich aroma, and authentic heat. Stone-ground to preserve essential oils. No additives, no preservatives, no artificial colors.","100% Pure Red Chili (Capsicum annuum)","Ideal for curries, BBQ marinades, and everyday cooking. Add 1 tsp per serving for perfect heat. Store in a cool, dry place.",True,False,True),
                ("golden-turmeric","Golden Turmeric Powder (Pisi Haldi)","Stone-ground pure turmeric",180,220,"200g","/static/uploads/product02.jpeg","Turmeric Powder","High-curcumin turmeric powder stone-ground from premium Pakistani roots. Golden-yellow color with earthy aroma. Sourced from family farms in Sindh. Naturally anti-inflammatory and packed with antioxidants.","100% Pure Turmeric Root (Curcuma longa)","Use in curries, milk (haldi doodh), and wellness drinks. Add 1/2 tsp daily for health benefits. Pairs well with black pepper for better absorption.",True,False,True),
                ("fresh-coriander","Fresh Coriander Powder (Pisa Dhaniya)","Aromatic & finely milled",160,190,"200g","/static/uploads/product03.jpeg","Coriander Powder","Finely ground coriander powder from select Pakistani farms. Citrusy aroma with mild, warming flavor. Essential for authentic Pakistani and Indian cooking. Freshly ground in small batches.","100% Pure Coriander Seeds (Coriandrum sativum)","Essential for dals, curries, and spice blends. Toast lightly in a dry pan before use for enhanced flavor. Add 1 tsp per serving.",False,True,True),
                ("black-pepper-powder","Black Pepper Powder (Pisi Kali Mirch)","Freshly ground, bold & pungent",190,230,"100g","/static/uploads/product09.jpeg","Premium Blends","Premium black pepper powder from carefully selected peppercorns. Bold, pungent aroma with a sharp kick. Perfect for everyday seasoning and finishing dishes. No fillers or additives.","100% Pure Black Pepper (Piper nigrum)","Use as a table spice or in cooking. Add 1/4 tsp per serving. Grind fresh for best results. Essential for garam masala and spice blends.",False,True,True),
                ("chaat-masala","Tangy Chaat Masala","Street-style zing",140,170,"100g","/static/uploads/product05.jpeg","Premium Blends","Zesty, tangy masala that brings authentic street food flavor to your home. Perfect for fruits, salads, yogurt, and snacks. Our signature blend combines mango powder, black salt, and aromatic spices.","Cumin, Coriander, Mango Powder (Amchur), Black Salt (Kala Namak), Red Chili, Ginger, Mint, Black Pepper, Citric Acid","Sprinkle on fruit chaat, salads, yogurt, or use as a finishing spice for any snack. Also great on grilled corn and roasted nuts.",True,False,True),
                ("pink-salt","Himalayan Pink Salt (Gulabi Namak)","Pure, mineral-rich rock salt",120,150,"200g","/static/uploads/product06.jpeg","Salt Range","Premium Himalayan pink salt mined from the Khewra Salt Mine — the second largest salt mine in the world. Rich in trace minerals including potassium, magnesium, and calcium. Chemical-free and unrefined.","100% Natural Himalayan Pink Salt","Use as a finishing salt, in cooking, or in salt grinders. Also great for salt therapy and bath soaks. Replace regular table salt for a healthier alternative.",False,False,True),
                ("rock-salt","Rock Salt (Kala Namak)","Authentic sulfurous mineral salt",110,140,"200g","/static/uploads/product07.jpeg","Salt Range","Traditional black mineral salt with characteristic sulfurous aroma. Essential for authentic South Asian cuisine. Mined from natural deposits in Pakistan. A staple in chaat, raita, and chutneys.","100% Natural Black Mineral Salt","Crush before use. Essential for chaat masala, fruit salads, raita, and chutneys. Adds an egg-like flavor to vegan dishes. Use sparingly — 1/4 tsp is enough.",False,False,True),
                ("royal-garam-masala","Royal Garam Masala","Heritage 14-spice blend",250,300,"100g","/static/uploads/product08.jpeg","Garam Masala","Our signature blend of 14 hand-roasted and stone-ground spices. Cardamom, cinnamon, cloves, cumin, nutmeg, and more. Each batch is slow-roasted to unlock deep, complex flavors. No preservatives or artificial colors.","Cardamom (Green + Black), Cinnamon, Cloves, Cumin, Nutmeg, Mace, Black Pepper, Bay Leaf, Star Anise, Fennel, Coriander, Ginger, White Pepper","Add at the end of cooking for maximum aroma. Perfect for biryani, curries, korma, and lentil dishes. Use 1 tsp per kg of meat. Toast gently before adding for deeper flavor.",True,False,True),
            ]
            for p in prods:
                slug, name, tagline, price, old_price, weight, image, cat_name, desc, ing, use, bs, na, feat = p
                product = Product.objects.create(
                    slug=slug, name=name, tagline=tagline, price=price, old_price=old_price,
                    weight=weight, image=image, category_id=cat_map.get(cat_name, 1),
                    description=desc, ingredients=ing, usage=use, best_seller=bs, new_arrival=na, featured=feat
                )
                ProductVariant.objects.create(
                    product=product,
                    sku=f'AURA-{product.id}-default',
                    weight_value=Decimal(weight.lower().replace('kg', '').replace('g', '')),
                    weight_unit='kg' if weight.lower().endswith('kg') else 'g',
                    price=Decimal(str(price)),
                    old_price=Decimal(str(old_price)),
                    stock_quantity=100,
                )
            self.stdout.write('Products seeded')

        if Testimonial.objects.count() == 0:
            tests = [
                ("Ayesha K.","Karachi","The Kunri chili is unreal — the colour, the aroma, exactly what my mother used to buy from the village."),
                ("Bilal R.","Lahore","Switched my whole pantry to Aura. The garam masala makes a difference you can smell from the next room."),
                ("Sana M.","Islamabad","Beautifully packed, super fresh, and delivered in two days. The biryani masala is restaurant-grade."),
                ("Tariq A.","Rawalpindi","Ordered the BBQ bundle for a family gathering. Everyone asked where I got the spices!"),
                ("Fatima Z.","Faisalabad","Finally, organic spices I can trust. My children's food is now completely preservative-free."),
            ]
            for name, city, text in tests:
                Testimonial.objects.create(name=name, city=city, text=text, rating=5)
            self.stdout.write('Testimonials seeded')

        if BlogPost.objects.count() == 0:
            posts = [
                ("health-benefits-turmeric","The Health Benefits of Daily Turmeric","Wellness","4 min","Discover why golden turmeric is called the king of spices and how daily consumption can transform your health.","<p>Aura Foods is committed to bringing you the finest organic spices from Pakistan.</p><p>We believe that great food starts with great ingredients.</p>", "/static/images/turmeric.jpg"),
                ("perfect-bbq-spices","Best Spices for the Perfect BBQ Night","Cooking","6 min","Elevate your barbecue game with these essential spice blends and marinade techniques.","<p>The secret to an unforgettable BBQ lies in the spices. Our Smoky BBQ Rub is crafted with smoked paprika, cumin, and a secret blend of herbs.</p>", "/static/images/bbq.jpg"),
                ("sindh-spice-heritage","Inside Sindh: Pakistan's Spice Heritage","Heritage","5 min","Journey through the spice farms of Sindh and learn about Pakistan's rich culinary traditions.","<p>Sindh has been a spice-growing region for centuries.</p>", "/static/images/garam.jpg"),
            ]
            for slug, title, cat, read, excerpt, content, image in posts:
                BlogPost.objects.create(slug=slug, title=title, category=cat, read_time=read, excerpt=excerpt, content=content, image=image)
            self.stdout.write('Blog posts seeded')

        if Bundle.objects.count() == 0:
            Bundle.objects.create(name="BBQ Master Bundle", items="Smoky BBQ Rub + Chaat Masala + Red Chili", price=490, old_price=620, save_percent=21)
            Bundle.objects.create(name="Kitchen Essentials", items="Red Chili + Turmeric + Coriander Powder", price=430, old_price=540, save_percent=20)
            Bundle.objects.create(name="Biryani Night Pack", items="Biryani Masala + Garam Masala + Turmeric", price=560, old_price=690, save_percent=19)
            self.stdout.write('Bundles seeded')

        if WhyItem.objects.count() == 0:
            why = [
                ("leaf","100% Organic","Sourced from trusted Pakistani farms without synthetic chemicals."),
                ("shield","No Preservatives","Nothing artificial added. Ever. Just pure spice."),
                ("sparkles","No Artificial Colors","Pure pigment comes from the spice itself, not chemicals."),
                ("award","Hygienically Packed","Sealed in food-grade facilities with strict quality control."),
                ("truck","Fast Delivery","Across Pakistan in 2-4 business days. Track your order."),
                ("flame","Fresh Aroma","Ground in small batches weekly to preserve essential oils."),
            ]
            for i, (icon, title, desc) in enumerate(why):
                WhyItem.objects.create(icon=icon, title=title, description=desc, sort_order=i)
            self.stdout.write('Why items seeded')

        if DeliveryZone.objects.count() == 0:
            DeliveryZone.objects.create(
                name='Karachi Metro',
                city_pattern='karachi',
                base_charge=120,
                free_delivery_min=1500,
                estimated_days_min=1,
                estimated_days_max=2,
                courier_hint='Local courier',
                sort_order=1,
            )
            DeliveryZone.objects.create(
                name='Major Cities',
                city_pattern='lahore,islamabad,rawalpindi,faisalabad,hyderabad,multan,peshawar,quetta',
                base_charge=220,
                free_delivery_min=2500,
                estimated_days_min=2,
                estimated_days_max=4,
                courier_hint='National courier',
                sort_order=2,
            )
            DeliveryZone.objects.create(
                name='Rest of Pakistan',
                city_pattern='',
                base_charge=300,
                free_delivery_min=3000,
                estimated_days_min=3,
                estimated_days_max=6,
                courier_hint='National courier',
                sort_order=3,
            )
            self.stdout.write('Delivery zones seeded')

        if FAQItem.objects.count() == 0:
            faqs = [
                ('How is delivery calculated?', 'Delivery charges are calculated server-side by city and order subtotal. The final checkout total is authoritative.', 'Delivery', 1),
                ('Can I track my order?', 'Yes. Use the Track Order page with your order reference and phone number.', 'Delivery', 2),
                ('Can food products be returned?', 'Returns are reviewed for unopened, damaged, or incorrectly supplied products according to the published return policy.', 'Returns', 3),
                ('How do I request support?', 'Use the Support page or the Order Support link inside your customer account.', 'Support', 4),
                ('How should spices be stored?', 'Keep spices sealed, dry, and away from sunlight, heat, and moisture.', 'Product Care', 5),
            ]
            for question, answer, category, sort_order in faqs:
                FAQItem.objects.create(question=question, answer=answer, category=category, sort_order=sort_order)
            self.stdout.write('FAQ items seeded')

        if not SitePage.objects.exists():
            SitePage.objects.create(page='about', title='Our Story', subtitle='From the sun-drenched fields of Sindh to your kitchen')
            self.stdout.write('Site pages seeded')

        self.stdout.write(self.style.SUCCESS('Database seeded successfully!'))
