from django.contrib import admin
from .models import PayoutPeriod, PayoutBatch, Payout, PayoutLineItem, Payslip, PayoutHistory

@admin.register(PayoutPeriod)
class PayoutPeriodAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'status']
    list_filter = ['status', 'is_tax_year_end']


@admin.register(PayoutBatch)
class PayoutBatchAdmin(admin.ModelAdmin):
    list_display = ['reference_number', 'period', 'run_date', 'status', 'created_by']
    list_filter = ['status', 'period']
    search_fields = ['reference_number']


class PayoutLineItemInline(admin.TabularInline):
    model = PayoutLineItem
    readonly_fields = ['commission', 'amount']
    extra = 0
    can_delete = False


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ['consultant', 'batch', 'total_commission', 'net_amount', 'status', 'paid_at']
    list_filter = ['status', 'batch']
    search_fields = ['consultant__username', 'payment_reference']
    inlines = [PayoutLineItemInline]
    readonly_fields = ['total_commission', 'net_amount']
