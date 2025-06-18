param name string
param location string = resourceGroup().location
param tags object = {}

@description('The pricing tier of the Redis cache')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param skuName string = 'Basic'

@description('The SKU family for the Redis cache')
param skuFamily string = 'C'

@description('The cache capacity')
@minValue(0)
@maxValue(6)
param skuCapacity int = 0

resource redis 'Microsoft.Cache/redis@2023-08-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      name: skuName
      family: skuFamily
      capacity: skuCapacity
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

// Output the Redis connection details
@secure()
output connectionString string = 'redis://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:${redis.properties.sslPort}?ssl=true'
output hostName string = redis.properties.hostName
output sslPort int = redis.properties.sslPort
@secure()
output primaryKey string = redis.listKeys().primaryKey
output id string = redis.id
output name string = redis.name
