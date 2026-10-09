from django.core.management.base import BaseCommand

from event.models import Event


class Command(BaseCommand):
    help = (
        'Deactivate cancelled, completed, imminent, and past events. '
        'Run this command once per minute from the production scheduler.'
    )

    def handle(self, *args, **options):
        count = Event.deactivate_due_events()
        self.stdout.write(
            self.style.SUCCESS(f'Deactivated {count} event(s).')
        )
