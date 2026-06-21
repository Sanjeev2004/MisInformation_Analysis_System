import sqlite3
import datetime
from backend.database import init_db, get_db_connection

def seed_data():
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if database already has posts
    cursor.execute("SELECT COUNT(*) FROM posts")
    if cursor.fetchone()[0] > 0:
        print("Database already seeded. Skipping.")
        conn.close()
        return
        
    print("Seeding database...")
    
    # 1. Create Clusters
    clusters = [
        # (id, claim_title, main_entities, average_risk)
        (1, "COVID-19 vaccine causes infertility in women", "COVID-19 vaccine, fertility", 72.5),
        (2, "5G radiation causes or spreads COVID-19", "5G network, COVID-19", 83.0),
        (3, "Drinking bleach cures COVID-19", "bleach, COVID-19, cure", 92.0),
        (4, "JWST detects signs of vegetation on Exoplanet K2-18b", "JWST, K2-18b, NASA", 25.0)
    ]
    cursor.executemany(
        "INSERT INTO clusters (id, claim_title, main_entities, average_risk) VALUES (?, ?, ?, ?)",
        clusters
    )
    
    # 2. Create Posts
    # We will spread timestamps over the last 24 hours to simulate a trending feed
    now = datetime.datetime.now()
    t_minus_1h = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    t_minus_2h = (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    t_minus_3h = (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    t_minus_6h = (now - datetime.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    t_minus_12h = (now - datetime.timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
    t_minus_18h = (now - datetime.timedelta(hours=18)).strftime("%Y-%m-%d %H:%M:%S")
    
    posts = [
        # (id, text, claim_text, url, domain, verdict, confidence, overall_risk, explanation, timestamp, cluster_id)
        (
            1,
            "BREAKING NEWS: A peer-reviewed study EXPOSES that COVID-19 vaccines cause permanent infertility in 80% of young women! The government is HIDING the truth!",
            "COVID-19 vaccine causes infertility in women.",
            "http://www.naturalnews.com/vaccine-fertility-expose",
            "naturalnews.com",
            "Likely False",
            90.0,
            88.5,
            "Reason: The text uses highly sensational language ('EXPOSES', 'HIDING') and comes from a domain (naturalnews.com) known for spreading health misinformation. Additionally, multiple fact-checking organizations have thoroughly debunked the claim.",
            t_minus_1h,
            1
        ),
        (
            2,
            "Is it true that the coronavirus vaccine affects your fertility? I heard it causes sterility. Please share!",
            "COVID-19 vaccine causes infertility in women.",
            None,
            None,
            "Suspicious",
            50.0,
            56.5,
            "Reason: The text is a question rather than a direct claim, but it repeats a widely debunked rumor. While it contains low direct sensationalism, it lacks any supporting evidence.",
            t_minus_3h,
            1
        ),
        (
            3,
            "SHOCKING: 5G radiation weakens your cells allowing viruses like COVID to spread like wildfire. They are installing towers at night!",
            "5G mobile networks spread the coronavirus.",
            "http://www.infowars.com/5g-coronavirus-conspiracy",
            "infowars.com",
            "Likely False",
            95.0,
            91.0,
            "Reason: The text is from infowars.com (a domain flagged for false conspiracy theories) and uses panic-inducing words. WHO and Reuters have stated there is no connection between 5G electromagnetic waves and virus transmission.",
            t_minus_6h,
            2
        ),
        (
            4,
            "5G towers and the coronavirus: a scientific plot or a real threat? Let's check the facts.",
            "5G mobile networks spread the coronavirus.",
            "http://www.dailymail.co.uk/news/5g-coronvirus-debates",
            "dailymail.co.uk",
            "Suspicious",
            65.0,
            55.0,
            "Reason: This article adopts a clickbait heading that gives weight to conspiracy theories, although it cites both sides. Cites reputable sources indicating no health links, lowering overall risk.",
            t_minus_12h,
            2
        ),
        (
            5,
            "Warning: Please do NOT drink bleach or chlorine dioxide! It is an extremely dangerous hoax that does NOT cure COVID-19.",
            "Drinking chlorine dioxide or bleach cures COVID-19.",
            "https://www.fda.gov/consumers/consumer-updates/danger-dont-drink-miracle-mineral-solution",
            "fda.gov",
            "Likely True",
            85.0,
            15.0,
            "Reason: The content originates from a government safety agency (FDA) and directly refutes a dangerous health rumor, offering medical warnings and verified data.",
            t_minus_2h,
            3
        ),
        (
            6,
            "Drinking warm water with chlorine dioxide cures coronavirus instantly! A doctor told my friend. Pass this on!",
            "Drinking chlorine dioxide or bleach cures COVID-19.",
            None,
            None,
            "Likely False",
            90.0,
            89.0,
            "Reason: Cites an anonymous 'doctor friend' and promotes a dangerous, chemically toxic treatment. Contradicts warnings from health regulatory bodies.",
            t_minus_18h,
            3
        ),
        (
            7,
            "NASA's James Webb Space Telescope has detected signs of vegetation on the super-earth exoplanet K2-18b, suggesting the presence of chlorophyll.",
            "JWST detects signs of vegetation on Exoplanet K2-18b.",
            "https://apnews.com/article/nasa-jwst-space-exoplanet",
            "apnews.com",
            "Uncertain",
            55.0,
            25.0,
            "Reason: Published by a trusted agency (AP News) with neutral language. However, scientific consensus is uncertain, as data is preliminary and atmospheric signatures are still being debated.",
            t_minus_6h,
            4
        )
    ]
    cursor.executemany(
        "INSERT INTO posts (id, text, claim_text, url, domain, verdict, confidence, overall_risk, explanation, timestamp, cluster_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        posts
    )
    
    # 3. Create Evidence
    evidence = [
        # (id, post_id, title, snippet, url, source, type, similarity_score)
        (
            1, 1, 
            "No scientific evidence COVID-19 vaccine causes infertility",
            "PolitiFact checked and found zero empirical data supporting reports that vaccine antibodies target placental proteins.",
            "https://www.politifact.com/factchecks/2021/jan/11/facebook-posts/no-scientific-evidence-covid-19-vaccine-causes-in/",
            "PolitiFact", "refute", 0.92
        ),
        (
            2, 1,
            "No Evidence Vaccines Cause Infertility",
            "FactCheck.org confirmed that the spike protein in COVID-19 vaccines does not share genetic sequences with syncytin-1.",
            "https://www.factcheck.org/2021/01/scicheck-no-evidence-vaccines-cause-infertility/",
            "FactCheck.org", "refute", 0.88
        ),
        (
            3, 3,
            "5G mobile networks DO NOT spread COVID-19",
            "WHO Fact Sheet: Viruses cannot travel on radio waves or mobile networks. COVID-19 is spreading in many countries that do not have 5G networks.",
            "https://www.who.int/emergencies/diseases/novel-coronavirus-2019/advice-for-public/myth-busters",
            "WHO", "refute", 0.95
        ),
        (
            4, 3,
            "False claim: 5G technology causes coronavirus",
            "Reuters Fact Check: Scientists and health authorities confirm that electromagnetic waves do not transmit viruses.",
            "https://www.reuters.com/article/uk-factcheck-5g-idUSKBN21P2O1",
            "Reuters", "refute", 0.90
        ),
        (
            5, 5,
            "Danger: Don't Drink Miracle Mineral Solution",
            "FDA warning explaining that chlorine dioxide products can cause severe liver failure, low blood count, and death.",
            "https://www.fda.gov/consumers/consumer-updates/danger-dont-drink-miracle-mineral-solution-or-other-sodium-chlorite-products",
            "FDA", "support", 0.95
        ),
        (
            6, 7,
            "Webb telescope detects methane and carbon dioxide on K2-18b",
            "NASA Webb team announced the detection of carbon-bearing molecules but cautioned that suggestions of life are unconfirmed.",
            "https://apnews.com/article/nasa-jwst-space-exoplanet",
            "AP News", "support", 0.90
        )
    ]
    cursor.executemany(
        "INSERT INTO evidence (id, post_id, title, snippet, url, source, type, similarity_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        evidence
    )
    
    # 4. Create Highlights
    highlights = [
        # (id, post_id, phrase, category)
        (1, 1, "EXPOSES", "sensational"),
        (2, 1, "HIDING the truth", "fallacy"),
        (3, 1, "vaccines cause permanent infertility", "unverified"),
        (4, 3, "SHOCKING", "sensational"),
        (5, 3, "spread like wildfire", "sensational"),
        (6, 3, "installing towers at night", "unverified"),
        (7, 6, "cures coronavirus instantly", "unverified"),
        (8, 6, "doctor told my friend", "fallacy")
    ]
    cursor.executemany(
        "INSERT INTO highlights (id, post_id, phrase, category) VALUES (?, ?, ?, ?)",
        highlights
    )
    
    conn.commit()
    conn.close()
    print("Database seeded successfully!")

if __name__ == "__main__":
    seed_data()
