"""
Django management command for running analytics aggregation.
Can be scheduled via cron, Cloud Scheduler, or Celery Beat.

Usage:
    python manage.py run_analytics_rollup              # Daily only
    python manage.py run_analytics_rollup --all        # All applicable rollups
    python manage.py run_analytics_rollup --date=2026-01-19   # Specific date
"""
import logging
from datetime import datetime, date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from analytics.aggregation import AggregationEngine

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run analytics aggregation (daily, monthly, quarterly, annual rollups)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Target date (YYYY-MM-DD). Defaults to yesterday.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run all applicable rollups based on the date.',
        )
        parser.add_argument(
            '--daily',
            action='store_true',
            help='Run daily aggregation only.',
        )
        parser.add_argument(
            '--monthly',
            action='store_true',
            help='Force monthly rollup (regardless of date).',
        )
        parser.add_argument(
            '--quarterly',
            action='store_true',
            help='Force quarterly rollup (regardless of date).',
        )
        parser.add_argument(
            '--annual',
            action='store_true',
            help='Force annual rollup (regardless of date).',
        )
    
    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(self.style.NOTICE(
            f"Starting analytics aggregation at {start_time}"
        ))
        
        # Parse target date
        if options['date']:
            try:
                target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('Invalid date format. Use YYYY-MM-DD.')
        else:
            target_date = timezone.now().date()
        
        self.stdout.write(f"Target date: {target_date}")
        
        # Initialize engine
        engine = AggregationEngine(target_date=target_date)
        
        all_results = {}
        
        # Run daily aggregation
        if options['daily'] or options['all'] or not any([
            options['monthly'], options['quarterly'], options['annual']
        ]):
            self.stdout.write(self.style.HTTP_INFO('Running DAILY aggregation...'))
            daily_results = engine.run_daily_aggregation()
            all_results.update(daily_results)
            self._print_results('DAILY', daily_results)
        
        # Run monthly rollup
        if options['monthly'] or (options['all'] and target_date.day == 1):
            self.stdout.write(self.style.HTTP_INFO('Running MONTHLY rollup...'))
            monthly_results = engine.run_monthly_rollup()
            all_results.update(monthly_results)
            self._print_results('MONTHLY', monthly_results)
        
        # Run quarterly rollup
        if options['quarterly'] or (options['all'] and self._is_first_of_quarter(target_date)):
            self.stdout.write(self.style.HTTP_INFO('Running QUARTERLY rollup...'))
            quarterly_results = engine.run_quarterly_rollup()
            all_results.update(quarterly_results)
            self._print_results('QUARTERLY', quarterly_results)
        
        # Run annual rollup
        if options['annual'] or (options['all'] and target_date.month == 1 and target_date.day == 1):
            self.stdout.write(self.style.HTTP_INFO('Running ANNUAL rollup...'))
            annual_results = engine.run_annual_rollup()
            all_results.update(annual_results)
            self._print_results('ANNUAL', annual_results)
        
        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        total_created = sum(r.created for r in all_results.values())
        total_skipped = sum(r.skipped for r in all_results.values())
        total_errors = sum(len(r.errors) for r in all_results.values())
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Aggregation complete in {duration:.2f}s"
        ))
        self.stdout.write(f"  Total created: {total_created}")
        self.stdout.write(f"  Total skipped (duplicates): {total_skipped}")
        
        if total_errors > 0:
            self.stdout.write(self.style.WARNING(f"  Total errors: {total_errors}"))
            for key, result in all_results.items():
                for error in result.errors:
                    self.stdout.write(self.style.ERROR(f"    [{key}] {error}"))
        else:
            self.stdout.write(self.style.SUCCESS("  No errors"))
    
    def _print_results(self, window: str, results: dict):
        """Print results for a specific window."""
        for key, result in results.items():
            self.stdout.write(f"  {key}: {result}")
    
    def _is_first_of_quarter(self, d: date) -> bool:
        """Check if date is the first day of a quarter."""
        return d.day == 1 and d.month in [1, 4, 7, 10]
