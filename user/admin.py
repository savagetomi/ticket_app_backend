from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """Expose soft-deactivated accounts to authorized Django administrators."""

    list_display = (
        'email_address',
        'username',
        'first_name',
        'last_name',
        'roles',
        'email_verified',
        'is_active',
        'is_staff',
    )
    list_filter = ('is_active', 'roles', 'email_verified', 'is_staff', 'is_superuser')
    search_fields = ('email_address', 'username', 'first_name', 'last_name')
    ordering = ('email_address',)
    readonly_fields = ('created_at', 'updated_at', 'last_login', 'date_joined')
    actions = ('reactivate_accounts',)

    fieldsets = (
        (None, {'fields': ('email_address', 'password')}),
        ('Personal information', {
            'fields': ('first_name', 'last_name', 'username', 'phone_number'),
        }),
        ('Application status', {'fields': ('roles', 'email_verified')}),
        ('Location', {'fields': ('ip_address', 'city', 'country', 'latitude', 'longitude')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email_address',
                'username',
                'first_name',
                'last_name',
                'phone_number',
                'roles',
                'email_verified',
                'is_active',
                'is_staff',
                'is_superuser',
                'password1',
                'password2',
            ),
        }),
    )

    @admin.action(description='Reactivate selected deactivated accounts')
    def reactivate_accounts(self, request, queryset):
        reactivated = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f'{reactivated} account(s) reactivated.')

    def has_delete_permission(self, request, obj=None):
        """Keep Django admin from bypassing the account soft-delete policy."""
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        return actions
