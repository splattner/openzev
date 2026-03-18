from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from accounts.permissions import IsZevOwnerOrAdmin
from zev.models import Zev
from .models import Tariff, TariffPeriod
from .serializers import TariffSerializer, TariffPeriodSerializer


class TariffViewSet(viewsets.ModelViewSet):
    serializer_class = TariffSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return Tariff.objects.all()
        return Tariff.objects.filter(zev__owner=user)

    def _get_accessible_zev(self, zev_id):
        user = self.request.user
        if user.is_admin:
            return Zev.objects.filter(id=zev_id).first()
        return Zev.objects.filter(id=zev_id, owner=user).first()

    def _serialize_tariff_preset(self, tariff):
        return {
            'name': tariff.name,
            'category': tariff.category,
            'billing_mode': tariff.billing_mode,
            'energy_type': tariff.energy_type,
            'fixed_price_chf': str(tariff.fixed_price_chf) if tariff.fixed_price_chf is not None else None,
            'valid_from': tariff.valid_from.isoformat(),
            'valid_to': tariff.valid_to.isoformat() if tariff.valid_to else None,
            'notes': tariff.notes,
            'periods': [
                {
                    'period_type': period.period_type,
                    'price_chf_per_kwh': str(period.price_chf_per_kwh),
                    'time_from': period.time_from.isoformat() if period.time_from else None,
                    'time_to': period.time_to.isoformat() if period.time_to else None,
                    'weekdays': period.weekdays,
                }
                for period in tariff.periods.all()
            ],
        }

    @action(detail=False, methods=['get'], url_path='export')
    def export_tariffs(self, request):
        """Export all tariffs for a ZEV as JSON."""
        zev_id = request.query_params.get('zev_id')
        if not zev_id:
            return Response({'error': 'zev_id query parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        zev = self._get_accessible_zev(zev_id)
        if not zev:
            return Response({'error': 'ZEV not found or not accessible.'}, status=status.HTTP_404_NOT_FOUND)

        tariffs = self.get_queryset().filter(zev_id=zev_id)
        if not tariffs.exists():
            return Response({'error': 'No tariffs found for this ZEV.'}, status=status.HTTP_404_NOT_FOUND)

        return Response([self._serialize_tariff_preset(tariff) for tariff in tariffs])

    @action(detail=False, methods=['post'], url_path='import')
    def import_tariffs(self, request):
        """Import tariffs and periods from JSON data."""
        zev_id = request.data.get('zev_id')
        tariffs_data = request.data.get('tariffs', [])

        if not zev_id:
            return Response({'error': 'zev_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not tariffs_data:
            return Response({'error': 'tariffs array is required.'}, status=status.HTTP_400_BAD_REQUEST)

        zev = self._get_accessible_zev(zev_id)
        if not zev:
            return Response({'error': 'ZEV not found or not accessible.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            with transaction.atomic():
                created_tariffs = []
                for tariff_data in tariffs_data:
                    tariff_data = dict(tariff_data)
                    # Extract periods before creating tariff
                    periods_data = tariff_data.pop('periods', [])
                    tariff_data.pop('id', None)
                    tariff_data.pop('zev', None)
                    tariff_data.pop('created_at', None)
                    tariff_data.pop('updated_at', None)
                    # Set the ZEV ID
                    tariff_data['zev'] = str(zev.id)

                    # Create tariff
                    tariff_serializer = TariffSerializer(data=tariff_data)
                    if not tariff_serializer.is_valid():
                        raise Exception(f"Invalid tariff data: {tariff_serializer.errors}")
                    tariff = tariff_serializer.save()

                    # Create periods
                    for period_data in periods_data:
                        period_data = dict(period_data)
                        period_data.pop('id', None)
                        period_data.pop('tariff', None)
                        period_data['tariff'] = str(tariff.id)
                        period_serializer = TariffPeriodSerializer(data=period_data)
                        if not period_serializer.is_valid():
                            raise Exception(f"Invalid period data: {period_serializer.errors}")
                        period_serializer.save()

                    created_tariffs.append(tariff_serializer.data)

                return Response(
                    {'created': len(created_tariffs), 'tariffs': created_tariffs},
                    status=status.HTTP_201_CREATED
                )

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class TariffPeriodViewSet(viewsets.ModelViewSet):
    serializer_class = TariffPeriodSerializer
    permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.is_admin:
            return TariffPeriod.objects.all()
        return TariffPeriod.objects.filter(tariff__zev__owner=user)
