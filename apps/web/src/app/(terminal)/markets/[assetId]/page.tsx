import { AssetView } from "@/components/screens";
export default async function Page({params}: {params:Promise<{assetId:string}>}) { const {assetId}=await params; return <AssetView assetId={assetId}/>; }
