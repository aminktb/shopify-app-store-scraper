# -*- coding: utf-8 -*-
import scrapy
from scrapy import Request
import re
import uuid
import hashlib
from ..items import App, KeyBenefit, PricingPlan, PricingPlanFeature, Category, AppCategory, AppReview
from bs4 import BeautifulSoup
import pandas as pd


class AppStoreSpider(scrapy.spiders.SitemapSpider):
    REVIEWS_REGEX = r"(.*?)/reviews$"
    BASE_DOMAIN = "apps.shopify.com"

    name = 'app_store'

    allowed_domains = ['apps.shopify.com']
    sitemap_urls = ['https://apps.shopify.com/sitemap.xml']
    sitemap_rules = [
        (re.compile(REVIEWS_REGEX), 'parse')
    ]

    def parse(self, response):
        app_id = str(uuid.uuid4())
        app_url = re.compile(self.REVIEWS_REGEX).search(response.url).group(1)

        response.meta['app_id'] = app_id

        yield Request(app_url, callback=self.parse_app, meta={'app_id': app_id})
        for review in self.parse_reviews(response):
            yield review

    @staticmethod
    def close(spider, reason):
        spider.logger.info('Spider closed: %s', spider.name)
        spider.logger.info('Preparing unique categories...')

        # Normalize categories
        categories_df = pd.read_csv('output/categories.csv')
        categories_df.drop_duplicates(subset=['id', 'title']).to_csv('output/categories.csv', index=False)

        spider.logger.info('Unique categories are there 👌')
        return super().close(spider, reason)

    def parse_app(self, response):
        app_id = response.meta['app_id']

        url = response.request.url
        title = response.css('.vc-app-listing-hero__heading ::text').extract_first()
        developer = response.css('.vc-app-listing-hero__by-line a::text').extract_first()
        developer_link = response.css('.vc-app-listing-hero__by-line a::attr(href)').extract_first()
        icon = response.css('.vc-app-listing-about-tab__icon::attr(src)').extract_first()
        rating = response.css('.ui-star-rating__rating::text').extract_first()
        reviews_count = response.css('.ui-review-count-summary a::text').extract_first()
        description_raw = response.css('.ui-expandable-content .block').extract_first()
        description = ' '.join(response.css('.ui-expandable-content .block ::text').extract()).strip()
        tagline = ' '.join(response.css('.vc-app-listing-hero__tagline ::text').extract()).strip()
        pricing_hint = (response.css('.app-listing-title__sub-heading ::text').extract_first() or '').strip()

        for benefit in response.css('.vc-app-listing-key-values__item'):
            yield KeyBenefit(app_id=app_id, title=benefit.css('.vc-app-listing-key-values__item-title ::text').extract_first().strip(),
                             description=benefit.css('.vc-app-listing-key-values__item-description ::text').extract_first().strip())

        for pricing_plan in response.css('.ui-card.pricing-plan-card'):
            pricing_plan_id = str(uuid.uuid4())
            yield PricingPlan(id=pricing_plan_id,
                              app_id=app_id,
                              title=(pricing_plan.css('.pricing-plan-card__title-kicker ::text').extract_first() or '').strip(),
                              subtitle=(pricing_plan.css('.pricing-plan-card__title-sub-heading ::text').extract_first() or '').strip(),
                              price=pricing_plan.css('.pricing-plan-card__title-header ::text').extract_first().strip())

            for feature in pricing_plan.css('.pricing-plan-card__details-list li'):
                yield PricingPlanFeature(pricing_plan_id=pricing_plan_id, app_id=app_id,
                                         feature=feature.css('::text').getall()[-1].strip())

        for category in response.css('.vc-app-listing-hero__taxonomy-links a::text').extract():
            category_id = hashlib.md5(category.lower().encode()).hexdigest()

            yield Category(id=category_id, title=category)
            yield AppCategory(app_id=app_id, category_id=category_id)

        yield App(
            id=app_id,
            url=url,
            title=title,
            developer=developer,
            developer_link=developer_link,
            icon=icon,
            rating=rating,
            reviews_count=int(next(iter(re.findall(r'\d+', str(reviews_count))), '0')),
            description_raw=description_raw,
            description=description,
            tagline=tagline,
            pricing_hint=pricing_hint
        )

    def parse_reviews(self, response):
        app_id = response.meta['app_id']

        for review in response.css('div.review-listing'):
            author = (review.css('.review-listing-header>h3 ::text').extract_first() or '').strip()
            rating = (review.css(
                '.review-metadata>div:nth-child(1) .ui-star-rating::attr(data-rating)').extract_first() or '').strip()
            posted_at = (review.css(
                '.review-metadata>div:nth-child(2) .review-metadata__item-value ::text').extract_first() or '').strip()
            body = BeautifulSoup(review.css('.review-content div').extract_first(), features='lxml').get_text().strip()
            helpful_count = review.css('.review-helpfulness .review-helpfulness__helpful-count ::text').extract_first()
            developer_reply = BeautifulSoup(
                review.css('.review-reply .review-content div').extract_first() or '',
                features='lxml').get_text().strip()
            developer_reply_posted_at = (review.css(
                '.review-reply div.review-reply__header-item ::text').extract_first() or '').strip()

            yield AppReview(
                app_id=app_id,
                author=author,
                rating=rating,
                posted_at=posted_at,
                body=body,
                helpful_count=helpful_count,
                developer_reply=developer_reply,
                developer_reply_posted_at=developer_reply_posted_at
            )

        next_page_path = response.css('a.search-pagination__next-page-text::attr(href)').extract_first()
        if next_page_path:
            yield Request('https://{}{}'.format(self.BASE_DOMAIN, next_page_path), callback=self.parse_reviews,
                          meta={'app_id': response.meta['app_id']})
